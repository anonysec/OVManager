// Per-user traffic accounting pass over all active nodes
// (design docs/plans/2026-10-19-usage-accounting-live-snapshot-design.md §4.3).
package node

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"sync"

	"github.com/anonysec/OVManager/go/internal/billing"
)

// TrafficResult summarizes one SyncTraffic pass.
type TrafficResult struct {
	NodesPolled  int
	NodesFailed  int
	UsersUpdated int
	UsersSeeded  int
	BytesBilled  int64
	// AliasCollisions names the (user, node) pairs where the node reported
	// more than one key for the same user. The bytes are summed (see
	// SyncTraffic), but the collision is reported so a node whose keying has
	// drifted is visible instead of silent.
	AliasCollisions []string
	// AmbiguousKeys identifies usage keys that could refer to two different
	// users (a numeric ID and a legacy username). They are not billed until
	// the ambiguity is resolved, rather than charging the wrong account.
	AmbiguousKeys []string
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
	ambiguous := map[int64]map[string]bool{}
	// aliasKeys remembers the first reported key per (user, node) so a
	// collision can name both keys.
	aliasKeys := map[int64]map[string]string{}
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
			// Reserved keys (push_hash, __epochs) exist only inside stored
			// node_usage bookkeeping. A reported username that happens to
			// be "push_hash" is a real user and must be billed.
			// Older nodes report names, newer ones report numeric IDs. A
			// numeric name may also be another user's ID; the payload has no
			// way to disambiguate it, so do not guess and charge either user.
			name := billing.ExtractUsername(reported, n.Name, known)
			idKey := reported
			if _, ok := idToName[idKey]; !ok {
				idKey = strings.TrimSuffix(reported, "-"+n.Name)
			}
			if mapped, ok := idToName[idKey]; ok {
				if known[name] && name != mapped {
					res.AmbiguousKeys = append(res.AmbiguousKeys,
						fmt.Sprintf("node=%s key=%s users=%s,%s", n.Name, reported, name, mapped))
					for _, u := range []trafficUser{byName[name], byName[mapped]} {
						if ambiguous[u.id] == nil {
							ambiguous[u.id] = map[string]bool{}
						}
						ambiguous[u.id][nodeKey] = true
					}
					continue
				}
				name = mapped
			}
			u, ok := byName[name]
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
				res.AliasCollisions = append(res.AliasCollisions,
					fmt.Sprintf("user=%s node=%s keys=%s,%s", u.name, nodeKey, aliasKeys[u.id][nodeKey], reported))
			} else {
				contribs[u.id][nodeKey] = cur
				contribEpochs[u.id][nodeKey] = reportedEpoch
			}
			if aliasKeys[u.id] == nil {
				aliasKeys[u.id] = map[string]string{}
			}
			if _, ok := aliasKeys[u.id][nodeKey]; !ok {
				aliasKeys[u.id][nodeKey] = reported
			}
		}
	}

	for _, u := range users {
		c := contribs[u.id]
		// Skip the entire node contribution for both affected users, even
		// if another alias was also reported, to keep their baselines intact.
		for key := range ambiguous[u.id] {
			delete(c, key)
		}
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
func applyTrafficUser(db *sql.DB, u trafficUser, contribs map[string]int64, epochs map[string]string) (billed, seeded bool, bytes int64) {
	used, state := u.used, u.state
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			if err := db.QueryRow(
				`SELECT COALESCE(used,0), COALESCE(node_usage,'{}') FROM users WHERE id = ?`, u.id,
			).Scan(&used, &state); err != nil {
				return false, false, 0
			}
		}
		if trafficTestHook != nil {
			trafficTestHook()
		}

		data := decodeUsageState(state)
		_, reseed := data[ReseedMarkerKey]
		if reseed {
			// Invalidate *all* old baselines, including nodes that did not
			// answer this pass. Each node will seed independently when it
			// next reports, rather than billing its pre-reset traffic.
			for key := range data {
				if !IsReservedUsageKey(key) {
					delete(data, key)
				}
			}
			// Invalidate offline-node epochs as well: drop epoch entries for
			// nodes that are not in this pass.
			if em, ok := data[EpochsKey].(map[string]any); ok {
				for key := range em {
					if _, present := contribs[key]; !present {
						delete(em, key)
					}
				}
				if len(em) == 0 {
					delete(data, EpochsKey)
				} else {
					data[EpochsKey] = em
				}
			}
			delete(data, ReseedMarkerKey)
		}

		// stored epochs
		storedEpochs := map[string]any{}
		if em, ok := data[EpochsKey].(map[string]any); ok {
			for k, v := range em {
				storedEpochs[k] = v
			}
		}

		newUsed := used
		var delta int64
		didSeed := false
		epochChanged := false
		for key, cur := range contribs {
			if cur < 0 {
				continue
			}
			reportedEpoch := ""
			if epochs != nil {
				reportedEpoch = epochs[key]
			}
			prev, present := toInt64(data[key])
			prevEpoch := toStringValue(storedEpochs[key])

			if reseed || !present {
				// seed
				data[key] = cur
				didSeed = true
				if reportedEpoch != "" && toStringValue(storedEpochs[key]) != reportedEpoch {
					epochChanged = true
				}
				if reportedEpoch != "" {
					storedEpochs[key] = reportedEpoch
				}
				continue
			}

			explicitReset := false
			if reportedEpoch != "" && prevEpoch != "" && reportedEpoch != prevEpoch {
				explicitReset = true
			}
			// first epoch adoption: adopt without reset (explicitReset stays false)

			d, newBaseline := billing.ComputeTotalDelta(cur, prev, explicitReset)
			delta += d
			newUsed += d
			data[key] = newBaseline
			if explicitReset {
				didSeed = true
			}
			if reportedEpoch != "" && prevEpoch != reportedEpoch {
				epochChanged = true
			}
			if reportedEpoch != "" {
				storedEpochs[key] = reportedEpoch
			}
		}

		// persist epochs map if non-empty
		if len(storedEpochs) > 0 {
			data[EpochsKey] = storedEpochs
		} else {
			delete(data, EpochsKey)
		}

		if !reseed && !didSeed && delta == 0 && !epochChanged {
			return false, false, 0
		}

		tx, err := db.Begin()
		if err != nil {
			return false, false, 0
		}
		if !billing.ApplyUserTraffic(tx, u.id, used, state, newUsed, billing.Canon(data), delta) {
			_ = tx.Rollback()
			continue
		}
		if err := tx.Commit(); err != nil {
			_ = tx.Rollback()
			return false, false, 0
		}
		return delta > 0, didSeed, delta
	}
	return false, false, 0
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
		byName[u.name] = u
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
