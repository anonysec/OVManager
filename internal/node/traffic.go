// Per-user traffic accounting pass over all active nodes
// (design docs/plans/2026-10-19-usage-accounting-live-snapshot-design.md §4.3).
package node

import (
	"database/sql"
	"encoding/json"
	"fmt"
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
		calls = append(calls, func() any { return NodeClient(n, pid).GetUsage(NodeTimeout(n, share)) })
	}
	raw := GatherNodes(calls, trafficFanoutDeadline)

	contribs := map[int64]map[string]int64{}
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
		res.NodesPolled++
		nodeKey := strconv.FormatInt(n.ID, 10)
		for reported, rawTotal := range totals {
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
			cur, ok := toInt64(rawTotal)
			if !ok {
				continue
			}
			if contribs[u.id] == nil {
				contribs[u.id] = map[string]int64{}
			}
			// The node's /sync/usage merges alias CNs ADDITIVELY
			// (OVNode get_users_usage: users[key] = users.get(key, 0) +
			// total), so two reported keys that resolve to one user are two
			// DIFFERENT byte pools. They must be summed: keeping only the
			// larger one silently drops the other's bytes from users.used,
			// from user_traffic_daily and from the baseline, for good.
			if prev, seen := contribs[u.id][nodeKey]; seen {
				contribs[u.id][nodeKey] = prev + cur
				res.AliasCollisions = append(res.AliasCollisions,
					fmt.Sprintf("user=%s node=%s keys=%s,%s", u.name, nodeKey, aliasKeys[u.id][nodeKey], reported))
			} else {
				contribs[u.id][nodeKey] = cur
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
		billed, seeded, bytes := applyTrafficUser(db, u, c)
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
func applyTrafficUser(db *sql.DB, u trafficUser, contribs map[string]int64) (billed, seeded bool, bytes int64) {
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

		data := map[string]any{}
		if json.Unmarshal([]byte(state), &data) != nil {
			data = map[string]any{}
		}
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
			delete(data, ReseedMarkerKey)
		}

		newUsed := used
		var delta int64
		didSeed := false
		for key, cur := range contribs {
			prev, present := toInt64(data[key])
			if reseed || !present {
				data[key] = cur
				didSeed = true
				continue
			}
			d, _ := billing.ComputeSessionDelta(nil, prev, float64(cur))
			delta += int64(d)
			newUsed += int64(d)
			data[key] = cur
		}
		if !reseed && !didSeed && delta == 0 {
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
	return out, byName
}

// toInt64 reads a JSON scalar as int64; a non-scalar (or absent) value reports
// false so the caller treats the baseline as missing.
func toInt64(v any) (int64, bool) {
	switch n := v.(type) {
	case float64:
		return int64(n), true
	case int64:
		return n, true
	case int:
		return int64(n), true
	case json.Number:
		i, err := n.Int64()
		return i, err == nil
	}
	return 0, false
}
