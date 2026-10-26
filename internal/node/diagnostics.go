// Session diagnostics and login health monitoring
// (backend/node/diagnostics.py).
package node

import (
	"database/sql"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/billing"
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

func diagUserNameMaps(db *sql.DB) (map[string]string, map[string]bool) {
	names := map[string]string{}
	known := map[string]bool{}
	rows, err := db.Query(`SELECT id, name FROM users`)
	if err != nil {
		return names, known
	}
	defer rows.Close()
	for rows.Next() {
		var id int64
		var name string
		if rows.Scan(&id, &name) == nil {
			names[strconv.FormatInt(id, 10)] = name
			known[name] = true
		}
	}
	return names, known
}

// GetUserSessionDiagnostics aggregates one user's sessions across nodes.
func GetUserSessionDiagnostics(userID int64, db *sql.DB, hours int) map[string]any {
	var name string
	if err := db.QueryRow(`SELECT name FROM users WHERE id = ?`, userID).Scan(&name); err != nil {
		return map[string]any{"username": strconv.FormatInt(userID, 10), "found": false}
	}
	nodes := getActiveNodes(db)
	names, known := diagUserNameMaps(db)
	names[strconv.FormatInt(userID, 10)] = name
	known[name] = true
	pid := PanelIDFor(db)

	share := FairShareTimeout(RequestFanoutDeadline, len(nodes), NodeFanoutLimit)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			sessions := NodeClient(n, pid).GetSessions("", hours, share)
			return []any{n.Name, sessions}
		})
	}
	nodeRows := []any{}
	totalLive, totalStale, totalAuth, totalUserAuth := 0, 0, 0, 0
	unavailableNodes := 0
	for i, item := range GatherNodes(calls, RequestFanoutDeadline) {
		fallbackName := ""
		if i < len(nodes) && nodes[i] != nil {
			fallbackName = nodes[i].Name
		}
		nodeName, data := diagnosticNodeResult(item, fallbackName)
		if nodeName == "" {
			continue
		}
		if data == nil {
			unavailableNodes++
			nodeRows = append(nodeRows, map[string]any{"node": nodeName, "reachable": false})
			continue
		}
		live := filterUserCN(sessionList(data["live_sessions"]), name, nodeName, names, known)
		stale := filterUserCN(sessionList(data["stale_markers"]), name, nodeName, names, known)
		userAuth := userAuthErrorCount(data["auth_errors_by_cn"], name, nodeName, names, known)
		nodeRows = append(nodeRows, map[string]any{
			"node":               nodeName,
			"reachable":          true,
			"live_sessions":      live,
			"stale_markers":      stale,
			"live_count":         len(live),
			"stale_marker_count": len(stale),
			"auth_errors":        intOf(data["auth_errors"]),
			"auth_events":        userAuth,
		})
		totalLive += len(live)
		totalStale += len(stale)
		totalAuth += intOf(data["auth_errors"])
		totalUserAuth += userAuth
	}
	return map[string]any{
		"username":          name,
		"user_id":           userID,
		"found":             true,
		"nodes":             nodeRows,
		"partial":           unavailableNodes > 0,
		"unavailable_nodes": unavailableNodes,
		"total_nodes":       len(nodes),
		"totals": map[string]any{
			"live_count":         totalLive,
			"stale_marker_count": totalStale,
			"auth_errors":        totalAuth,
			"user_auth_errors":   totalUserAuth,
		},
	}
}

func filterUserCN(list []map[string]any, username, nodeName string, names map[string]string, known map[string]bool) []map[string]any {
	out := []map[string]any{}
	for _, session := range list {
		commonName, _ := session["common_name"].(string)
		if resolved(names, commonName, nodeName, known) == username {
			out = append(out, session)
		}
	}
	return out
}

func userAuthErrorCount(values any, username, nodeName string, names map[string]string, known map[string]bool) int {
	byCN, ok := values.(map[string]any)
	if !ok {
		return 0
	}
	total := 0
	for commonName, value := range byCN {
		if resolved(names, commonName, nodeName, known) == username {
			total += intOf(value)
		}
	}
	return total
}

func idxString(pair []any, i int) string {
	if i >= len(pair) {
		return ""
	}
	s, _ := pair[i].(string)
	return s
}

// diagnosticNodeResult keeps the configured node identity when a fan-out
// returns an error/timeout instead of the normal {name, data} pair.
func diagnosticNodeResult(result any, fallbackName string) (string, map[string]any) {
	pair, ok := result.([]any)
	if !ok || len(pair) < 2 {
		return fallbackName, nil
	}
	if name := idxString(pair, 0); name != "" {
		fallbackName = name
	}
	data, _ := pair[1].(map[string]any)
	return fallbackName, data
}

// LoginHealthSummary aggregates login health for every user with activity.
func LoginHealthSummary(db *sql.DB, hours int) map[string]any {
	users := diagUsers(db)
	nodes := getActiveNodes(db)
	names := make(map[string]string, len(users))
	known := make(map[string]bool, len(users))
	for _, u := range users {
		names[strconv.FormatInt(u.id, 10)] = u.name
		known[u.name] = true
	}
	pid := PanelIDFor(db)

	share := FairShareTimeout(RequestFanoutDeadline, len(nodes), NodeFanoutLimit)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			sessions := NodeClient(n, pid).GetSessions("", hours, share)
			return []any{n.Name, sessions}
		})
	}

	activeCounts := map[string]int{}
	staleCounts := map[string]int{}
	authCounts := map[string]int{}
	nodeRows := []any{}
	unavailableNodes := 0
	for i, item := range GatherNodes(calls, RequestFanoutDeadline) {
		fallbackName := ""
		if i < len(nodes) && nodes[i] != nil {
			fallbackName = nodes[i].Name
		}
		nodeName, data := diagnosticNodeResult(item, fallbackName)
		if nodeName == "" {
			continue
		}
		if data == nil {
			unavailableNodes++
			nodeRows = append(nodeRows, map[string]any{"node": nodeName, "reachable": false})
			continue
		}
		for _, sess := range sessionList(data["live_sessions"]) {
			cn, _ := sess["common_name"].(string)
			username := resolved(names, cn, nodeName, known)
			activeCounts[username]++
			if _, ok := staleCounts[username]; !ok {
				staleCounts[username] = 0
			}
		}
		for _, marker := range sessionList(data["stale_markers"]) {
			cn, _ := marker["common_name"].(string)
			staleCounts[resolved(names, cn, nodeName, known)]++
		}
		if byCN, ok := data["auth_errors_by_cn"].(map[string]any); ok {
			for cn, v := range byCN {
				authCounts[resolved(names, cn, nodeName, known)] += intOf(v)
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
		"users":             rows,
		"nodes":             nodeRows,
		"partial":           unavailableNodes > 0,
		"unavailable_nodes": unavailableNodes,
		"total_nodes":       len(nodes),
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

// userHealthRow derives the per-user summary from the same node snapshot as the
// session detail. This keeps LoginDiagnostics from issuing a second session
// fan-out merely to reconstruct one row of LoginHealthSummary.
func userHealthRow(u diagUser, diag map[string]any) map[string]any {
	totals, _ := diag["totals"].(map[string]any)
	active := intOf(totals["live_count"])
	stale := intOf(totals["stale_marker_count"])
	if active <= 0 && stale <= 0 {
		return nil
	}

	mode := "strict"
	if u.maxLogins == 0 {
		mode = "unlimited"
	} else if u.maxLogins == 1 {
		mode = "takeover"
	}
	full := u.maxLogins > 0 && active >= u.maxLogins
	status := "idle"
	switch {
	case !u.isActive:
		status = "inactive"
	case stale > 0:
		status = "stale"
	case full && mode == "strict":
		status = "full"
	case active > 0:
		status = "online"
	}
	return map[string]any{
		"name":               u.name,
		"user_id":            u.id,
		"active_connections": active,
		"max_logins":         u.maxLogins,
		"mode":               mode,
		"full":               full,
		"is_active":          u.isActive,
		"stale_markers":      stale,
		"auth_events":        intOf(totals["user_auth_errors"]),
		"status":             status,
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
	healthRow := userHealthRow(u, diag)

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
	if totals, ok := diag["totals"].(map[string]any); ok {
		active = intOf(totals["live_count"])
	}
	maxLogins := u.maxLogins
	var recommendation string
	partial, _ := diag["partial"].(bool)
	if partial {
		recommendation = "Node diagnostics are incomplete; counts include reachable nodes only."
	} else {
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
		"global_registry_error": "The panel does not currently collect global registry data.",
		"nodes":                 diag["nodes"],
		"partial":               diag["partial"],
		"unavailable_nodes":     diag["unavailable_nodes"],
		"total_nodes":           diag["total_nodes"],
		"totals":                diag["totals"],
		"health":                healthRow,
		"recommendation":        recommendation,
	}
}

func resolved(names map[string]string, commonName, nodeName string, known map[string]bool) string {
	return billing.ResolveSessionUsername(commonName, nodeName, names, known)
}

func expiredBefore(date string) bool {
	for _, layout := range []string{"2006-01-02", time.RFC3339, "2006-01-02 15:04:05"} {
		if t, err := time.Parse(layout, date); err == nil {
			return t.Before(time.Now().Truncate(24 * time.Hour))
		}
	}
	return false
}
