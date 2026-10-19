// Per-user traffic accounting pass over all active nodes
// (design docs/plans/2026-10-19-usage-accounting-live-snapshot-design.md §4.3).
package node

import (
	"database/sql"
	"encoding/json"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/go/internal/billing"
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

// SyncTraffic bills every user's cumulative node-total delta in one pass.
func SyncTraffic(db *sql.DB) TrafficResult {
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
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any { return NodeClient(n, pid).GetUsage(ProbeTimeout(n)) })
	}
	raw := GatherNodes(calls, trafficFanoutDeadline)

	contribs := map[int64]map[string]int64{}
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
		totals, ok := data["totals"].(map[string]any)
		if !ok {
			res.NodesFailed++
			continue
		}
		res.NodesPolled++
		nodeKey := strconv.FormatInt(n.ID, 10)
		for reported, rawTotal := range totals {
			resolved := reported
			if mapped, ok := idToName[reported]; ok {
				resolved = mapped
			} else {
				suffix := "-" + n.Name
				if strings.HasSuffix(reported, suffix) {
					base := reported[:len(reported)-len(suffix)]
					if mapped, ok := idToName[base]; ok {
						resolved = mapped + suffix
					}
				}
			}
			u, ok := byName[billing.ExtractUsername(resolved, n.Name, known)]
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
			if prev, seen := contribs[u.id][nodeKey]; !seen || cur > prev {
				contribs[u.id][nodeKey] = cur
			}
		}
	}

	for _, u := range users {
		c := contribs[u.id]
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
