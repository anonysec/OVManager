// Session diagnostics and login health monitoring
// (backend/node/diagnostics.py).
package node

import (
	"database/sql"
	"sort"
	"strconv"
	"strings"
	"time"
)

type diagUser struct {
	id        int64
	name      string
	isActive  bool
	maxLogins int
	total     sql.NullInt64
	used      int64
	expiry    sql.NullString
}

func diagUsers(db *sql.DB) []diagUser {
	rows, err := db.Query(`SELECT id, name, COALESCE(is_active,1), COALESCE(max_logins,0),
		total, COALESCE(used,0), expiry_date FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []diagUser
	for rows.Next() {
		var u diagUser
		if err := rows.Scan(&u.id, &u.name, &u.isActive, &u.maxLogins, &u.total, &u.used, &u.expiry); err != nil {
			return out
		}
		out = append(out, u)
	}
	return out
}

func idToName(db *sql.DB) map[string]string {
	out := map[string]string{}
	for _, u := range diagUsers(db) {
		out[strconv.FormatInt(u.id, 10)] = u.name
	}
	return out
}

// GetActiveConnectionCounts returns {username: live_connection_count}.
func GetActiveConnectionCounts(db *sql.DB) map[string]int {
	nodes := getActiveNodes(db)
	names := idToName(db)
	pid := PanelIDFor(db)
	counts := map[string]int{}

	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			return NodeClient(n, pid).GetSessions("", 1, ProbeTimeout(n))
		})
	}
	for _, item := range GatherNodes(calls, RequestFanoutDeadline) {
		data, ok := item.(map[string]any)
		if !ok {
			continue
		}
		for _, sess := range sessionList(data["live_sessions"]) {
			cn, _ := sess["common_name"].(string)
			username := cn
			if mapped, ok := names[cn]; ok {
				username = mapped
			}
			counts[username]++
		}
	}
	return counts
}

// GetUserSessionDiagnostics aggregates one user's sessions across nodes.
func GetUserSessionDiagnostics(userID int64, db *sql.DB, hours int) map[string]any {
	var name string
	if err := db.QueryRow(`SELECT name FROM users WHERE id = ?`, userID).Scan(&name); err != nil {
		return map[string]any{"username": strconv.FormatInt(userID, 10), "found": false}
	}
	nodes := getActiveNodes(db)
	pid := PanelIDFor(db)
	cn := strconv.FormatInt(userID, 10)

	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			sessions := NodeClient(n, pid).GetSessions("", hours, 0)
			return []any{n.Name, sessions}
		})
	}
	nodeRows := []any{}
	totalLive, totalStale, totalAuth := 0, 0, 0
	for _, item := range GatherNodes(calls, RequestFanoutDeadline) {
		pair, ok := item.([]any)
		if !ok || idxString(pair, 0) == "" {
			continue
		}
		nodeName := idxString(pair, 0)
		data, _ := pair[1].(map[string]any)
		if data == nil {
			nodeRows = append(nodeRows, map[string]any{"node": nodeName, "reachable": false})
			continue
		}
		live := filterCN(sessionList(data["live_sessions"]), cn)
		stale := filterCN(sessionList(data["stale_markers"]), cn)
		nodeRows = append(nodeRows, map[string]any{
			"node":               nodeName,
			"reachable":          true,
			"live_sessions":      live,
			"stale_markers":      stale,
			"live_count":         len(live),
			"stale_marker_count": len(stale),
			"auth_errors":        intOf(data["auth_errors"]),
		})
		totalLive += len(live)
		totalStale += len(stale)
		totalAuth += intOf(data["auth_errors"])
	}
	return map[string]any{
		"username": name,
		"user_id":  userID,
		"found":    true,
		"nodes":    nodeRows,
		"totals": map[string]any{
			"live_count":         totalLive,
			"stale_marker_count": totalStale,
			"auth_errors":        totalAuth,
		},
	}
}

func filterCN(list []map[string]any, cn string) []map[string]any {
	out := []map[string]any{}
	for _, s := range list {
		if c, _ := s["common_name"].(string); c == cn {
			out = append(out, s)
		}
	}
	return out
}

func idxString(pair []any, i int) string {
	if i >= len(pair) {
		return ""
	}
	s, _ := pair[i].(string)
	return s
}

// LoginHealthSummary aggregates login health for every user with activity.
func LoginHealthSummary(db *sql.DB, hours int) map[string]any {
	users := diagUsers(db)
	nodes := getActiveNodes(db)
	names := map[string]string{}
	for _, u := range users {
		names[strconv.FormatInt(u.id, 10)] = u.name
	}
	pid := PanelIDFor(db)

	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			sessions := NodeClient(n, pid).GetSessions("", hours, 0)
			return []any{n.Name, sessions}
		})
	}

	activeCounts := map[string]int{}
	staleCounts := map[string]int{}
	authCounts := map[string]int{}
	nodeRows := []any{}
	for _, item := range GatherNodes(calls, RequestFanoutDeadline) {
		pair, ok := item.([]any)
		if !ok || idxString(pair, 0) == "" {
			continue
		}
		nodeName := idxString(pair, 0)
		data, _ := pair[1].(map[string]any)
		if data == nil {
			nodeRows = append(nodeRows, map[string]any{"node": nodeName, "reachable": false})
			continue
		}
		for _, sess := range sessionList(data["live_sessions"]) {
			cn, _ := sess["common_name"].(string)
			username := resolved(names, cn)
			activeCounts[username]++
			if _, ok := staleCounts[username]; !ok {
				staleCounts[username] = 0
			}
		}
		for _, marker := range sessionList(data["stale_markers"]) {
			cn, _ := marker["common_name"].(string)
			staleCounts[resolved(names, cn)]++
		}
		if byCN, ok := data["auth_errors_by_cn"].(map[string]any); ok {
			for cn, v := range byCN {
				authCounts[resolved(names, cn)] += intOf(v)
			}
		}
		nodeRows = append(nodeRows, map[string]any{
			"node":               nodeName,
			"live_count":         intOf(data["live_count"]),
			"stale_marker_count": intOf(data["stale_marker_count"]),
			"auth_errors":        intOf(data["auth_errors"]),
			"reachable":          true,
		})
	}

	rows := []map[string]any{}
	for _, u := range users {
		active := activeCounts[u.name]
		maxLogins := u.maxLogins
		mode := "strict"
		if maxLogins == 0 {
			mode = "unlimited"
		} else if maxLogins == 1 {
			mode = "takeover"
		}
		full := maxLogins > 0 && active >= maxLogins
		var status string
		switch {
		case !u.isActive:
			status = "inactive"
		case staleCounts[u.name] > 0:
			status = "stale"
		case full && mode == "strict":
			status = "full"
		case active > 0:
			status = "online"
		default:
			status = "idle"
		}
		staleCount := staleCounts[u.name]
		if active <= 0 && staleCount <= 0 {
			continue
		}
		rows = append(rows, map[string]any{
			"name":               u.name,
			"user_id":            u.id,
			"active_connections": active,
			"max_logins":         maxLogins,
			"mode":               mode,
			"full":               full,
			"is_active":          u.isActive,
			"stale_markers":      staleCount,
			"auth_events":        authCounts[u.name],
			"status":             status,
		})
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		as, _ := a["status"].(string)
		bs, _ := b["status"].(string)
		if (as == "stale") != (bs == "stale") {
			return as == "stale"
		}
		ai, _ := a["active_connections"].(int)
		bi, _ := b["active_connections"].(int)
		if ai != bi {
			return ai > bi
		}
		an, _ := a["name"].(string)
		bn, _ := b["name"].(string)
		return strings.ToLower(an) < strings.ToLower(bn)
	})

	online, fullCount, staleSum, takeover := 0, 0, 0, 0
	for _, r := range rows {
		if ac, _ := r["active_connections"].(int); ac > 0 {
			online++
		}
		if f, _ := r["full"].(bool); f {
			fullCount++
		}
		if s, _ := r["stale_markers"].(int); s > 0 {
			staleSum += s
		}
		if m, _ := r["mode"].(string); m == "takeover" {
			takeover++
		}
	}
	return map[string]any{
		"users": rows,
		"nodes": nodeRows,
		"totals": map[string]any{
			"shown":         len(rows),
			"users":         len(users),
			"online":        online,
			"full":          fullCount,
			"stale":         staleSum,
			"takeover_mode": takeover,
		},
	}
}

// LoginDiagnostics is the per-user login diagnostic payload.
func LoginDiagnostics(name string, db *sql.DB, hours int) map[string]any {
	var u diagUser
	err := db.QueryRow(`SELECT id, name, COALESCE(is_active,1), COALESCE(max_logins,0),
		total, COALESCE(used,0), expiry_date FROM users WHERE name = ?`, name).
		Scan(&u.id, &u.name, &u.isActive, &u.maxLogins, &u.total, &u.used, &u.expiry)
	if err != nil {
		return map[string]any{"username": name, "found": false}
	}
	diag := GetUserSessionDiagnostics(u.id, db, hours)
	health := LoginHealthSummary(db, hours)
	var healthRow map[string]any
	if list, ok := health["users"].([]map[string]any); ok {
		for _, row := range list {
			if n, _ := row["name"].(string); n == name {
				healthRow = row
				break
			}
		}
	}

	policy := []string{}
	if !u.isActive {
		policy = append(policy, "inactive")
	}
	if u.expiry.Valid && expiredBefore(u.expiry.String) {
		policy = append(policy, "expired")
	}
	if u.total.Valid && u.used >= u.total.Int64 {
		policy = append(policy, "traffic_limit_reached")
	}
	if len(policy) == 0 {
		policy = append(policy, "ok")
	}

	active := 0
	if healthRow != nil {
		active, _ = healthRow["active_connections"].(int)
	} else if totals, ok := diag["totals"].(map[string]any); ok {
		active = intOf(totals["live_count"])
	}
	maxLogins := u.maxLogins
	var recommendation string
	switch {
	case maxLogins == 0:
		recommendation = "Unlimited login mode; no max-login block expected."
	case maxLogins == 1:
		recommendation = "Takeover mode: new connection should disconnect old session and be allowed."
	case active >= maxLogins:
		recommendation = "Strict mode is full; disconnect a session or increase max logins."
	default:
		recommendation = "User is below max-login limit. If connection fails, check node logs/config."
	}
	mode := "strict"
	if maxLogins == 0 {
		mode = "unlimited"
	} else if maxLogins == 1 {
		mode = "takeover"
	}
	return map[string]any{
		"username":              name,
		"found":                 true,
		"policy":                policy,
		"max_logins":            maxLogins,
		"mode":                  mode,
		"active_connections":    active,
		"global_registry":       []any{},
		"global_registry_error": nil,
		"nodes":                 diag["nodes"],
		"totals":                diag["totals"],
		"health":                healthRow,
		"recommendation":        recommendation,
	}
}

func resolved(names map[string]string, cn string) string {
	if n, ok := names[cn]; ok {
		return n
	}
	return cn
}

func expiredBefore(date string) bool {
	for _, layout := range []string{"2006-01-02", time.RFC3339, "2006-01-02 15:04:05"} {
		if t, err := time.Parse(layout, date); err == nil {
			return t.Before(time.Now().Truncate(24 * time.Hour))
		}
	}
	return false
}
