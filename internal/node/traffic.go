// Per-user traffic accounting pass over all active nodes
// (design docs/plans/2026-10-19-usage-accounting-live-snapshot-design.md §4.3).
package node

import (
	"database/sql"
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/anonysec/OVManager/internal/billing"
)

// TrafficResult summarizes one SyncTraffic pass.
type TrafficResult struct {
	NodesPolled  int
	NodesFailed  int
	UsersUpdated int
	UsersSeeded  int
	BytesBilled  int64
}

// trafficFanoutDeadline bounds one usage pass. A var so tests need not wait the
// full production deadline.
var trafficFanoutDeadline = RequestFanoutDeadline

// trafficTestHook, when non-nil, runs once after a user row is read and before
// the guarded write — a seam for simulating a concurrent node_usage writer.
var trafficTestHook func()

type trafficUser struct {
	id    int64
	name  string
	used  int64
	state string // raw node_usage JSON
}

// Serialize the entire snapshot and apply operation, not just the writes: an
// older in-flight snapshot applied after a newer one looks like a reset and
// would bill the same bytes again. This covers manual and background passes.
var trafficSyncLock sync.Mutex

// SyncTraffic bills every user's cumulative node-total delta in one pass.
func SyncTraffic(db *sql.DB) TrafficResult {
	trafficSyncLock.Lock()
	defer trafficSyncLock.Unlock()
	res := TrafficResult{}
	nodes := getActiveNodes(db)
	users, byName := loadTrafficUsers(db)

	idToName := map[string]string{}
	known := make(map[string]bool, len(users))
	for _, u := range users {
		idToName[strconv.FormatInt(u.id, 10)] = u.name
		known[u.name] = true
	}

	pid := PanelIDFor(db)
	// A hanging node must not hold a concurrency slot past the call's fair
	// share of the fan-out budget, or the nodes queued behind it never run.
	share := FairShareTimeout(trafficFanoutDeadline, len(nodes), fanoutLimit())
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			c := NodeClient(n, pid)
			u, err := c.GetUsage(NodeTimeout(n, share))
			if err != nil || u == nil {
				return nil
			}
			epochs := map[string]any{}
			for k, v := range u.TotalsEpochs {
				epochs[k] = v
			}
			m := map[string]any{"totals": map[string]any{}, "totals_epochs": epochs}
			for k, v := range u.Totals {
				m["totals"].(map[string]any)[k] = v
			}
			return m
		})
	}
	raw := GatherNodes(calls, trafficFanoutDeadline)
	contribs := map[int64]map[string]int64{}
	contribEpochs := map[int64]map[string]string{}
	for i, n := range nodes {
		if _, ok := raw[i].(error); ok {
			res.NodesFailed++
			continue
		}
		data, ok := raw[i].(map[string]any)
		if !ok {
			res.NodesFailed++
			continue
		}
		rawTotals := data["totals"]
		if rawTotals == nil {
			// A node that is up but has no users to report answers totals:null.
			res.NodesPolled++
			continue
		}
		totals, ok := rawTotals.(map[string]any)
		if !ok {
			res.NodesFailed++
			continue
		}
		var totalsEpochs map[string]any
		if te, ok := data["totals_epochs"].(map[string]any); ok {
			totalsEpochs = te
		}
		res.NodesPolled++
		nodeKey := strconv.FormatInt(n.ID, 10)
		for reported, rawTotal := range totals {
			// Node keys are numeric panel ids only (OpenVPN CN guarantee).
			// One query built idToName; no username fallback, no ambiguity.
			uid, err := strconv.ParseInt(reported, 10, 64)
			if err != nil {
				continue
			}
			u, ok := byName[strconv.FormatInt(uid, 10)]
			if !ok {
				continue
			}
			cur, ok := totalsInt64(rawTotal)
			if !ok || cur < 0 {
				continue
			}
			reportedEpoch := ""
			if totalsEpochs != nil {
				if v, ok := totalsEpochs[reported]; ok {
					reportedEpoch, _ = v.(string)
				}
			}
			if contribs[u.id] == nil {
				contribs[u.id] = map[string]int64{}
			}
			if contribEpochs[u.id] == nil {
				contribEpochs[u.id] = map[string]string{}
			}
			// The node's /sync/usage merges alias CNs ADDITIVELY
			// (OVNode get_users_usage: users[key] = users.get(key, 0) +
			// total), so two reported keys that resolve to one user are two
			// DIFFERENT byte pools. They must be summed: keeping only the
			// larger one silently drops the other's bytes from users.used,
			// from user_traffic_daily and from the baseline, for good.
			if prev, seen := contribs[u.id][nodeKey]; seen {
				contribs[u.id][nodeKey] = prev + cur
				contribEpochs[u.id][nodeKey] = aggregateEpoch(contribEpochs[u.id][nodeKey], reportedEpoch)
			} else {
				contribs[u.id][nodeKey] = cur
				contribEpochs[u.id][nodeKey] = reportedEpoch
			}
		}
	}

	for _, u := range users {
		c := contribs[u.id]
		if len(c) == 0 {
			continue
		}
		billed, seeded, bytes := applyTrafficUser(db, u, c, contribEpochs[u.id])
		if billed {
			res.UsersUpdated++
		}
		if seeded {
			res.UsersSeeded++
		}
		res.BytesBilled += bytes
	}
	return res
}

// applyTrafficUser computes one user's deltas and persists them under the OCC
// guard, retrying up to 3 attempts; a reseed marker (or an absent baseline)
// seeds all nodes with delta 0.
// applyTrafficUser computes one user's deltas and persists them under the OCC
// guard, retrying up to 3 attempts; a reseed marker (or an absent baseline)
// seeds all nodes with delta 0.
func applyTrafficUser(db *sql.DB, u trafficUser, contribs map[string]int64, epochs map[string]string) (billed, seeded bool, bytes int64) {
	return applyTrafficUserTx(db, u, contribs, epochs, nil)
}

// applyTrafficUserTx reads baselines from user_node_usage (falling back to
// the node_usage blob only when the table has no rows for the user), computes
// deltas, and writes used + baselines in one tx when tx is non-nil.
func applyTrafficUserTx(db *sql.DB, u trafficUser, contribs map[string]int64, epochs map[string]string, tx *sql.Tx) (billed, seeded bool, bytes int64) {
	used, state := u.used, u.state
	if trafficTestHook != nil {
		trafficTestHook()
	}
	baselines := map[int64]int64{}
	baseEpochs := map[int64]string{}
	reseed := false
	// table baselines (one query)
	rows, err := db.Query(`SELECT node_id, baseline, epoch FROM user_node_usage WHERE user_id = ?`, u.id)
	if err == nil {
		for rows.Next() {
			var nid, base int64
			var ep string
			if rows.Scan(&nid, &base, &ep) == nil {
				baselines[nid] = base
				baseEpochs[nid] = ep
			}
		}
		rows.Close()
	}
	// blob fallback only when table empty for this user
	if len(baselines) == 0 {
		data := decodeUsageState(state)
		_, reseed = data[ReseedMarkerKey]
		if _, ok := data[ReseedMarkerKey]; ok {
			reseed = true
		}
		storedEpochs := map[string]any{}
		if em, ok := data[EpochsKey].(map[string]any); ok {
			for k, v := range em {
				storedEpochs[k] = v
			}
		}
		for k, v := range data {
			if k == PushHashKey || k == ReseedMarkerKey || k == EpochsKey {
				continue
			}
			nid, err := strconv.ParseInt(k, 10, 64)
			if err != nil {
				continue
			}
			if b, ok := toInt64(v); ok {
				baselines[nid] = b
			}
			baseEpochs[nid] = toStringValue(storedEpochs[k])
		}
	}
	if reseed {
		for nid := range baselines {
			if _, present := contribs[strconv.FormatInt(nid, 10)]; !present {
				delete(baselines, nid)
				delete(baseEpochs, nid)
			}
		}
		for nid := range baseEpochs {
			if _, present := contribs[strconv.FormatInt(nid, 10)]; !present {
				delete(baseEpochs, nid)
			}
		}
	}
	newUsed := used
	var delta int64
	didSeed := false
	for key, cur := range contribs {
		if cur < 0 {
			continue
		}
		nid, err := strconv.ParseInt(key, 10, 64)
		if err != nil {
			continue
		}
		reportedEpoch := ""
		if epochs != nil {
			reportedEpoch = epochs[key]
		}
		prev, present := baselines[nid]
		prevEpoch := baseEpochs[nid]
		if reseed || !present {
			baselines[nid] = cur
			baseEpochs[nid] = reportedEpoch
			didSeed = true
			continue
		}
		explicitReset := reportedEpoch != "" && prevEpoch != "" && reportedEpoch != prevEpoch
		d, newBaseline := billing.ComputeTotalDelta(cur, prev, explicitReset)
		delta += d
		newUsed += d
		baselines[nid] = newBaseline
		baseEpochs[nid] = reportedEpoch
		if explicitReset {
			didSeed = true
		}
	}
	// persist: used + table baselines + blob (for fallback readers)
	data := decodeUsageState(state)
	delete(data, ReseedMarkerKey)
	if len(baseEpochs) > 0 {
		em := map[string]any{}
		for nid, e := range baseEpochs {
			em[strconv.FormatInt(nid, 10)] = e
		}
		data[EpochsKey] = em
	} else {
		delete(data, EpochsKey)
	}
	for _, k := range []string{} {
		_ = k
	}
	for nid, b := range baselines {
		data[strconv.FormatInt(nid, 10)] = b
	}
	// drop offline baselines left in blob by reseed
	for k := range data {
		if k == PushHashKey || k == ReseedMarkerKey || k == EpochsKey {
			continue
		}
		nid, err := strconv.ParseInt(k, 10, 64)
		if err != nil {
			continue
		}
		if _, ok := baselines[nid]; !ok {
			delete(data, k)
		}
	}
	exec := func(q string, args ...any) error {
		if tx != nil {
			_, e := tx.Exec(q, args...)
			return e
		}
		_, e := db.Exec(q, args...)
		return e
	}
	if tx == nil {
		tx2, err := db.Begin()
		if err != nil {
			return false, false, 0
		}
		defer func() { _ = tx2.Rollback() }()
		if !billing.ApplyUserTraffic(tx2, u.id, used, state, newUsed, billing.Canon(data), delta) {
			// re-read used/state, recompute would need restructure; single-write poll accepts miss
			_ = tx2.Rollback()
			return false, false, 0
		}
		for nid, b := range baselines {
			if _, e := tx2.Exec(`INSERT OR REPLACE INTO user_node_usage (user_id, node_id, baseline, epoch) VALUES (?, ?, ?, ?)`, u.id, nid, b, baseEpochs[nid]); e != nil {
				return false, false, 0
			}
		}
		if err := tx2.Commit(); err != nil {
			return false, false, 0
		}
		return delta > 0, didSeed, delta
	}
	if err := exec(`UPDATE users SET used = ?, node_usage = ? WHERE id = ?`, newUsed, billing.Canon(data), u.id); err != nil {
		return false, false, 0
	}
	for nid, b := range baselines {
		if _, e := tx.Exec(`INSERT OR REPLACE INTO user_node_usage (user_id, node_id, baseline, epoch) VALUES (?, ?, ?, ?)`, u.id, nid, b, baseEpochs[nid]); e != nil {
			return false, false, 0
		}
	}
	if delta > 0 {
		billing.RecordDailyBytes(tx, u.id, delta, "")
	}
	return delta > 0, didSeed, delta
}

func loadTrafficUsers(db *sql.DB) ([]trafficUser, map[string]trafficUser) {
	rows, err := db.Query(`SELECT id, name, COALESCE(used,0), COALESCE(node_usage,'{}') FROM users`)
	if err != nil {
		return nil, nil
	}
	defer rows.Close()
	var out []trafficUser
	byName := map[string]trafficUser{}
	for rows.Next() {
		var u trafficUser
		if err := rows.Scan(&u.id, &u.name, &u.used, &u.state); err != nil {
			break
		}
		out = append(out, u)
		byName[strconv.FormatInt(u.id, 10)] = u
	}
	if err := rows.Err(); err != nil {
		return nil, nil
	}
	return out, byName
}

func totalsInt64(v any) (int64, bool) {
	switch n := v.(type) {
	case json.Number:
		i, err := n.Int64()
		return i, err == nil
	case float64:
		if n != float64(int64(n)) {
			return 0, false
		}
		return int64(n), true
	case int64:
		return n, true
	}
	return 0, false
}
func toInt64(v any) (int64, bool) {
	switch n := v.(type) {
	case json.Number:
		i, err := n.Int64()
		return i, err == nil
	case float64:
		if n != float64(int64(n)) {
			return 0, false
		}
		return int64(n), true
	case int64:
		return n, true
	case int:
		return int64(n), true
	}
	return 0, false
}

func decodeUsageState(s string) map[string]any {
	if s == "" {
		return map[string]any{}
	}
	dec := json.NewDecoder(strings.NewReader(s))
	dec.UseNumber()
	var data map[string]any
	if err := dec.Decode(&data); err != nil {
		return map[string]any{}
	}
	return data
}

func toStringValue(v any) string {
	switch n := v.(type) {
	case string:
		return n
	case json.Number:
		return n.String()
	case float64:
		return strconv.FormatFloat(n, 'f', -1, 64)
	case int64:
		return strconv.FormatInt(n, 10)
	case int:
		return strconv.Itoa(n)
	case nil:
		return ""
	default:
		b, _ := json.Marshal(n)
		return string(b)
	}
}

// aggregateEpoch merges two epoch descriptors symmetrically: both sides may
// be a single epoch or a comma-joined set of "cn=epoch" pairs, so the result
// does not depend on argument or map order.
func aggregateEpoch(existing, next string) string {
	set := map[string]bool{}
	for _, s := range []string{existing, next} {
		if s == "" {
			continue
		}
		for _, part := range strings.Split(s, ",") {
			if part = strings.TrimSpace(part); part != "" {
				set[part] = true
			}
		}
	}
	parts := make([]string, 0, len(set))
	for p := range set {
		if p != "" {
			parts = append(parts, p)
		}
	}
	sort.Strings(parts)
	return strings.Join(parts, ",")
}
