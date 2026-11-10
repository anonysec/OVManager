// Per-user traffic accounting pass over all active nodes.
// Simplified: node reports cumulative bytes per panel user id; panel overwrites
// users.used with the summed total. No baselines, no ledger, no daily table.
package node

import (
	"encoding/json"
	"database/sql"
	"strconv"
	"sync"
	"time"

)

// TrafficResult summarizes one SyncTraffic pass.
type TrafficResult struct {
	NodesPolled  int
	NodesFailed  int
	UsersUpdated int
	UsersSeeded  int
	BytesBilled  int64
}

// trafficFanoutDeadline bounds one usage pass.
var trafficFanoutDeadline = RequestFanoutDeadline

var trafficSyncLock sync.Mutex

type trafficUser struct {
	id   int64
	name string
}

func SyncTraffic(db *sql.DB) TrafficResult {
	trafficSyncLock.Lock()
	defer trafficSyncLock.Unlock()
	res := TrafficResult{}
	nodes := getActiveNodes(db)
	users, byID := loadTrafficUsers(db)

	pid := PanelIDFor(db)
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
			m := map[string]any{"totals": map[string]any{}}
			for k, v := range u.Totals {
				m["totals"].(map[string]any)[k] = v
			}
			return m
		})
	}
	raw := GatherNodes(calls, trafficFanoutDeadline)

	// Aggregate per-user totals across nodes.
	totals := map[int64]int64{}
	for i := range nodes {
		if _, ok := raw[i].(error); ok {
			res.NodesFailed++
			continue
		}
		data, ok := raw[i].(map[string]any)
		if !ok {
			res.NodesFailed++
			continue
		}
		_ = data["totals_epochs"]
		rawTotals := data["totals"]
		if rawTotals == nil {
			res.NodesPolled++
			continue
		}
		t, ok := rawTotals.(map[string]any)
		if !ok {
			res.NodesFailed++
			continue
		}
		res.NodesPolled++
		for reported, rawTotal := range t {
			uid, err := strconv.ParseInt(reported, 10, 64)
			if err != nil {
				continue
			}
			cur, ok := totalsInt64(rawTotal)
			if !ok || cur < 0 {
				continue
			}
			totals[uid] += cur
		}
	}

	// Apply traffic reset schedule and write used.
	now := time.Now().UTC()
	for _, u := range users {
		total := totals[u.id]
		// traffic reset check
		var trafficReset string
		var lastReset int64
		_ = db.QueryRow(`SELECT COALESCE(traffic_reset,'never'), COALESCE(last_traffic_reset,0) FROM users WHERE id = ?`, u.id).Scan(&trafficReset, &lastReset)
		if shouldResetTraffic(trafficReset, lastReset, now) {
			total = 0
			_, _ = db.Exec(`UPDATE users SET used = 0, last_traffic_reset = ? WHERE id = ?`, now.Unix(), u.id)
		}
		_, _ = db.Exec(`UPDATE users SET used = ? WHERE id = ?`, total, u.id)
		res.UsersUpdated++
		res.BytesBilled += total
	}
	_ = byID
	return res
}

func loadTrafficUsers(db *sql.DB) ([]trafficUser, map[int64]trafficUser) {
	rows, err := db.Query(`SELECT id, name FROM users`)
	if err != nil {
		return nil, nil
	}
	defer rows.Close()
	var users []trafficUser
	byID := map[int64]trafficUser{}
	for rows.Next() {
		var u trafficUser
		if rows.Scan(&u.id, &u.name) == nil {
			users = append(users, u)
			byID[u.id] = u
		}
	}
	return users, byID
}

func shouldResetTraffic(schedule string, lastReset int64, now time.Time) bool {
	if schedule == "never" || lastReset == 0 {
		return false
	}
	last := time.Unix(lastReset, 0).UTC()
	switch schedule {
	case "daily":
		return now.Day() != last.Day() || now.Month() != last.Month() || now.Year() != last.Year()
	case "weekly":
		_, nowWeek := now.ISOWeek()
		_, lastWeek := last.ISOWeek()
		return nowWeek != lastWeek || now.Year() != last.Year()
	case "monthly":
		return now.Month() != last.Month() || now.Year() != last.Year()
	}
	return false
}

func totalsInt64(v any) (int64, bool) {
	switch x := v.(type) {
	case float64:
		return int64(x), true
	case json.Number:
		n, err := x.Int64()
		if err != nil {
			return 0, false
		}
		return n, true
	case int64:
		return x, true
	case int:
		return int64(x), true
	}
	return 0, false
}

