package panel

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/internal/node"
)

// Security summary (backend). Aggregates per-node login
// diagnostics, re-classifying lines from nodes that predate structured events.

const (
	securityOngoingWindowS = 3600
	securityEventsLimit    = 100
	securityLastErrors     = 50
	securityTopNames       = 20
)

var (
	securityCNRe          = regexp.MustCompile(`CN=([^\s]+)`)
	securityLimitRe       = regexp.MustCompile(`(?:limit|global_limit)=([^\s;]+)`)
	securityActiveRe      = regexp.MustCompile(`(?:global_active|active_files)=([^\s;]+)`)
	securityMsgRe         = regexp.MustCompile(`msg=([^\n]+)$`)
	securityTimeRe        = regexp.MustCompile(`^([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})`)
	securityRejectLimitRe = regexp.MustCompile(`\blimit=`)
)

// panelTimezone is _get_panel_tz: the operator-configured zone, else UTC.
func (h *Handler) panelTimezone() *time.Location {
	name := strings.TrimSpace(h.settings().strOr("timezone"))
	if name == "" {
		name = "UTC"
	}
	loc, err := time.LoadLocation(name)
	if err != nil {
		return time.UTC
	}
	return loc
}

// classifyLogLine is _classify_line — the same severity split the node applies,
// kept here so a node that predates the classification release is still
// reported honestly.
func classifyLogLine(message string) (action, severity, reason string) {
	table := []struct{ needle, action, severity, reason string }{
		{"is disabled", "disabled", "policy", "user disabled in the panel"},
		{"disabled;", "disabled", "policy", "user disabled in the panel"},
		{"USERS_DIR missing", "fail_closed", "failure", "node user state missing"},
		{"could not verify", "takeover_failed", "failure", "old session not terminated"},
		{"management unavailable", "mgmt_degraded", "warn", "management unavailable"},
		{"GLOBAL_CHECK_FAILED", "global_check", "policy", "panel policy check failed"},
		{"GLOBAL_REJECT", "global_policy", "policy", "panel rejected the connection"},
		{"max login reached", "max_logins", "policy", "max logins reached"},
	}
	for _, row := range table {
		if strings.Contains(message, row.needle) {
			return row.action, row.severity, row.reason
		}
	}
	if strings.Contains(message, "REJECT") && securityRejectLimitRe.MatchString(message) {
		return "max_logins", "policy", "max logins reached"
	}
	if strings.Contains(message, "REJECT") {
		return "other", "warn", "unclassified reject"
	}
	if strings.Contains(message, "FAILED") {
		return "check_failed", "warn", "policy check failed"
	}
	return "event", "policy", "session event"
}

// parseLogLine is _parse_log_line: converts a raw ovnode-mlogin line to a clean
// event object. Only used for nodes older than the classification release.
func parseLogLine(line, commonName string, tz *time.Location) map[string]any {
	if tz == nil {
		tz = time.UTC
	}
	cn := commonName
	if m := securityCNRe.FindStringSubmatch(line); m != nil {
		cn = m[1]
	}
	action, severity, reason := classifyLogLine(line)

	var limit, active any
	if m := securityLimitRe.FindStringSubmatch(line); m != nil {
		limit = m[1]
	}
	if m := securityActiveRe.FindStringSubmatch(line); m != nil {
		active = m[1]
	}
	reasonText := reason
	if m := securityMsgRe.FindStringSubmatch(line); m != nil {
		reasonText = strings.TrimSpace(m[1])
	}

	ts := 0.0
	var localTime any
	if m := securityTimeRe.FindStringSubmatch(line); m != nil {
		year := strconv.Itoa(time.Now().UTC().Year())
		parsed, err := time.Parse("2006 Jan 2 15:04:05", year+" "+m[1]+" "+m[2]+" "+m[3])
		if err == nil {
			utc := parsed.UTC()
			ts = float64(utc.Unix())
			localTime = utc.In(tz).Format("2006-01-02 15:04:05")
		}
	}
	return map[string]any{
		"ts": ts, "time_local": localTime, "common_name": cn,
		"action": action, "severity": severity, "active": active, "limit": limit,
		"reason": reasonText, "line": line,
	}
}

// legacyEvents is _legacy_events: events from a node that predates structured
// diagnostics. Flagged unclassified so the UI can say the exact numbers arrive
// after an update.
func legacyEvents(s *node.SessionsResponse, nodeName string, tz *time.Location, idToName map[string]string) []map[string]any {
	raw := []map[string]any{}
	if len(s.LastError) > 0 {
		var le map[string]any
		if err := json.Unmarshal(s.LastError, &le); err == nil {
			keys := make([]string, 0, len(le))
			for k := range le {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				text, _ := le[k].(string)
				raw = append(raw, parseLogLine(text, k, tz))
			}
		} else {
			var leStr string
			if err := json.Unmarshal(s.LastError, &leStr); err == nil && leStr != "" {
				raw = append(raw, parseLogLine(leStr, "", tz))
			}
		}
	}

	now := float64(time.Now().UTC().UnixNano()) / 1e9
	rows := []map[string]any{}
	for _, ev := range raw {
		cn, _ := ev["common_name"].(string)
		ts := numberOr(ev["ts"], 0)
		known, ok := idToName[cn]
		user := cn
		if ok {
			user = known
		}
		rows = append(rows, map[string]any{
			"node": nodeName, "cn": cn, "user": user, "user_known": ok,
			"action":     stringOr(ev["action"], "event"),
			"severity":   stringOr(ev["severity"], "warn"),
			"reason":     stringOr(ev["reason"], "connection rejected"),
			"peer":       "",
			"ts":         ts,
			"time_local": ev["time_local"],
			"ongoing":    ts != 0 && now-ts <= securityOngoingWindowS,
			"classified": false,
		})
	}
	return rows
}

// nodeEvents is _node_events: the structured diagnostics a current node sends.
func nodeEvents(s *node.SessionsResponse, nodeName string, tz *time.Location, idToName map[string]string) []map[string]any {
	now := float64(time.Now().UTC().UnixNano()) / 1e9
	rows := []map[string]any{}
	for _, ev := range s.Events {
		cn := ev.CN
		peer := ev.Peer
		ts := ev.TS
		knownUser, known := "", false
		if cn != "" {
			knownUser, known = idToName[cn]
		}
		var userKnown any
		if cn != "" {
			userKnown = known
		}
		user := knownUser
		if user == "" {
			user = cn
		}
		if user == "" {
			user = peer
		}
		var localTime any
		if ts != 0 {
			localTime = time.Unix(int64(ts), 0).In(tz).Format("2006-01-02 15:04:05")
		}
		ongoing := ts != 0 && now-ts <= securityOngoingWindowS
		if len(ev.Ongoing) > 0 {
			var b bool
			if err := json.Unmarshal(ev.Ongoing, &b); err == nil {
				ongoing = b
			}
		}
		rows = append(rows, map[string]any{
			"node": nodeName, "cn": cn, "user": user, "user_known": userKnown,
			"action": ev.Action, "severity": ev.Severity, "reason": ev.Reason,
			"peer": peer, "ts": ts, "time_local": localTime, "ongoing": ongoing, "classified": true,
		})
	}
	return rows
}

// allNodes loads every node row (crud.get_all_nodes).
func (h *Handler) allNodes() []*node.Node {
	rows, err := h.Svc.DB().QueryContext(context.Background(),
		`SELECT id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca
		 FROM Node ORDER BY id`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []*node.Node{}
	for rows.Next() {
		if n := scanNodeRow(rows); n != nil {
			out = append(out, n)
		}
	}
	return out
}

// panelIDToName is _cn_to_username: numeric user id -> username.
func panelIDToName(db *sql.DB) map[string]string {
	out := map[string]string{}
	rows, err := db.Query(`SELECT id, name FROM User`)
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var id int64
		var name string
		if rows.Scan(&id, &name) == nil {
			out[strconv.FormatInt(id, 10)] = name
		}
	}
	return out
}

// securitySummary is GET /security/summary.
func (h *Handler) securitySummary(w http.ResponseWriter, r *http.Request) {
	// Server-side clamp: an arbitrary hours value here becomes identical
	// GetSessions work on every node.
	hours := intQuery(r, "hours", 8)
	if hours < 1 {
		hours = 1
	} else if hours > 48 {
		hours = 48
	}
	tz := h.panelTimezone()
	idToName := panelIDToName(h.Svc.DB())
	pid := node.PanelIDFor(h.Svc.DB())
	nodes := h.allNodes()

	share := node.FairShareTimeout(node.RequestFanoutDeadline, len(nodes), node.NodeFanoutLimit)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			s, _ := node.NodeClient(n, pid).GetSessions("", hours, share)
			return []any{n.Name, s}
		})
	}

	perNode := []map[string]any{}
	events := []map[string]any{}
	unclassified := []string{}
	totals := map[string]int{
		"auth_failures": 0, "policy_rejects": 0, "warn_events": 0, "stale_markers": 0, "rejects": 0,
	}

	for _, item := range node.GatherNodes(calls, node.RequestFanoutDeadline) {
		pair, ok := item.([]any)
		if !ok || len(pair) < 2 {
			continue
		}
		nodeName, _ := pair[0].(string)
		sess, _ := pair[1].(*node.SessionsResponse)
		if sess == nil {
			continue
		}
		stale := sess.StaleMarkerCount
		rejects := sess.Rejects
		hasEvents := len(sess.Events) > 0

		var nodeEventsList []map[string]any
		if hasEvents {
			nodeEventsList = nodeEvents(sess, nodeName, tz, idToName)
		} else {
			nodeEventsList = legacyEvents(sess, nodeName, tz, idToName)
		}

		var authFailures, policyRejects, warnEvents int
		classified := hasEvents
		if hasEvents {
			authFailures = sess.AuthErrors
			policyRejects = sess.PolicyRejects
			warnEvents = sess.WarnRejects
		} else {
			seenFailures, seenWarns := 0, 0
			for _, e := range nodeEventsList {
				switch e["severity"] {
				case "failure":
					seenFailures++
				case "warn":
					seenWarns++
				}
			}
			authFailures = seenFailures
			warnEvents = seenWarns
			policyRejects = rejects - seenFailures - seenWarns
			if policyRejects < 0 {
				policyRejects = 0
			}
		}

		totals["auth_failures"] += authFailures
		totals["policy_rejects"] += policyRejects
		totals["warn_events"] += warnEvents
		totals["stale_markers"] += stale
		totals["rejects"] += rejects
		if !classified {
			unclassified = append(unclassified, nodeName)
		}

		ongoing := 0
		for _, e := range nodeEventsList {
			if ongoingFlag, _ := e["ongoing"].(bool); ongoingFlag {
				ongoing++
			}
		}
		events = append(events, nodeEventsList...)
		perNode = append(perNode, map[string]any{
			"node": nodeName, "auth_errors": authFailures, "auth_failures": authFailures,
			"policy_rejects": policyRejects, "warn_events": warnEvents, "rejects": rejects,
			"stale_markers": stale, "live": sess.LiveCount,
			"ongoing": ongoing, "classified": classified,
		})
	}

	sort.SliceStable(events, func(i, j int) bool {
		return numberOr(events[i]["ts"], 0) > numberOr(events[j]["ts"], 0)
	})

	envelope(w, true, "Security summary", map[string]any{
		"hours":              hours,
		"timezone":           tz.String(),
		"auth_errors":        totals["auth_failures"],
		"auth_failures":      totals["auth_failures"],
		"policy_rejects":     totals["policy_rejects"],
		"warn_events":        totals["warn_events"],
		"rejects":            totals["rejects"],
		"stale_markers":      totals["stale_markers"],
		"per_node":           perNode,
		"events":             headEvents(events, securityEventsLimit),
		"ongoing_users":      ongoingUsers(events),
		"unclassified_nodes": unclassified,
		"last_errors":        headEvents(events, securityLastErrors),
		"top_common_names":   topCommonNames(events),
	})
}

// headEvents is events[:n].
func headEvents(events []map[string]any, n int) []map[string]any {
	if len(events) > n {
		return events[:n]
	}
	return events
}

// ongoingUsers is sorted({e.user for e in events if e.ongoing and e.user}).
func ongoingUsers(events []map[string]any) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, e := range events {
		if action, _ := e["action"].(string); action == "max_logins" {
			continue
		}
		flag, _ := e["ongoing"].(bool)
		user, _ := e["user"].(string)
		if flag && user != "" && !seen[user] {
			seen[user] = true
			out = append(out, user)
		}
	}
	sort.Strings(out)
	return out
}

// topCommonNames is Counter(user).most_common(20): count desc, ties in
// first-encountered order, rendered as [name, count] pairs.
func topCommonNames(events []map[string]any) [][]any {
	counts := map[string]int{}
	order := []string{}
	for _, e := range events {
		user, _ := e["user"].(string)
		if user == "" {
			continue
		}
		if _, seen := counts[user]; !seen {
			order = append(order, user)
		}
		counts[user]++
	}
	sort.SliceStable(order, func(i, j int) bool { return counts[order[i]] > counts[order[j]] })
	if len(order) > securityTopNames {
		order = order[:securityTopNames]
	}
	out := make([][]any, 0, len(order))
	for _, name := range order {
		out = append(out, []any{name, counts[name]})
	}
	return out
}

// --- small coercions (the node payload arrives as decoded JSON) ---

func stringOr(v any, def string) string {
	if s, ok := v.(string); ok && s != "" {
		return s
	}
	return def
}

func numberOr(v any, def float64) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	}
	return def
}
