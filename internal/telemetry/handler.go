package telemetry

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/notify"
)

// DefaultBus is the process-wide live event bus (live.bus).
var DefaultBus = NewBus()

// Publish fans an invalidation event out on the default bus (live.publish).
func Publish(topic string, data ...KV) { DefaultBus.Publish(topic, data...) }

// Handler serves the telemetry routes.
type Handler struct {
	Svc *auth.Service
}

// NewHandler builds the telemetry router.
func NewHandler(svc *auth.Service) *Handler { return &Handler{Svc: svc} }

// Mount registers the telemetry routes relative to the caller's prefix.
func (h *Handler) Mount(mux *http.ServeMux) {
	guard := h.Svc.RequireUser
	owner := h.Svc.RequireOwner
	mux.HandleFunc("GET /activity/", guard(h.activity))
	mux.HandleFunc("GET /metrics/history", owner(h.metricsHistory))
	mux.HandleFunc("POST /metrics/collect", owner(h.collectNow))
	mux.HandleFunc("GET /notifications/", guard(h.notifications))
	mux.HandleFunc("GET /live/stream", StreamHandler(h.Svc, DefaultBus))
}

// --- activity (routers/telemetry.py get_activity) ---

func (h *Handler) activity(w http.ResponseWriter, r *http.Request) {
	ident, _ := h.Svc.CurrentUser(r)
	var actor *string
	if ident.Type != "owner" {
		username := ident.Username
		actor = &username
	}
	limit := intQuery(r, "limit", 100)
	var action *string
	if a := r.URL.Query().Get("action"); a != "" {
		action = &a
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true, Msg: "Activity retrieved",
		Data: recentEvents(h.Svc.DB(), limit, actor, action),
	})
}

// recentEvents mirrors audit.recent_events.
func recentEvents(db *sql.DB, limit int, actor, action *string) []map[string]any {
	limit = clamp(limit, 1, 500)
	where := ""
	args := []any{}
	if actor != nil {
		where += " AND actor = ?"
		args = append(args, *actor)
	}
	if action != nil && *action != "" {
		where += ` AND action LIKE ? ESCAPE '\'`
		args = append(args, escapeLike(*action)+"%")
	}
	rows, err := db.Query(
		`SELECT id, ts, actor, action, target, detail FROM audit_logs WHERE 1=1`+where+` ORDER BY ts DESC LIMIT ?`,
		append(args, limit)...,
	)
	if err != nil {
		return []map[string]any{}
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var ts float64
		var a, act, target, detail sql.NullString
		if rows.Scan(&id, &ts, &a, &act, &target, &detail) != nil {
			continue
		}
		out = append(out, map[string]any{
			"id": id, "ts": ts, "actor": nullStr(a), "action": act.String,
			"target": nullStr(target), "detail": nullStr(detail),
		})
	}
	return out
}

// --- notifications (routers/telemetry.py notifications) ---

// INBOXTypes: threshold types that surface in the inbox (usage is Telegram-only).
var inboxTypes = map[string]bool{"threshold_expiry": true, "threshold_cpu": true}

func (h *Handler) notifications(w http.ResponseWriter, r *http.Request) {
	items := []map[string]any{}
	rows, err := h.Svc.DB().Query(`SELECT name, status FROM nodes ORDER BY id`)
	if err == nil {
		for rows.Next() {
			var name string
			var status sql.NullInt64
			if rows.Scan(&name, &status) == nil && status.Int64 == 0 {
				items = append(items, map[string]any{
					"level": "danger", "type": "node_offline",
					"title": "Node " + name + " is offline", "target": name,
				})
			}
		}
		rows.Close()
	}
	for _, item := range thresholdItems(h.Svc.DB()) {
		if t, _ := item["type"].(string); inboxTypes[t] {
			items = append(items, item)
		}
	}
	if len(items) > 100 {
		items = items[:100]
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Notifications", Data: items})
}

// --- thresholds (observability/thresholds.py) ---

const (
	defaultDaysLeft = 3
	defaultUsagePct = 80
	defaultCPUPct   = 85
)

// activeKinds are every kind threshold_items can emit.
var activeKinds = []string{"threshold_expiry", "threshold_usage", "threshold_cpu"}

// thresholdItems mirrors thresholds.threshold_items.
func thresholdItems(db *sql.DB) []map[string]any {
	s := readSettings(db)
	items := []map[string]any{}

	if s.notifyExpiry {
		days := clamp(s.alertDaysLeft, 0, 365)
		today := time.Now().UTC().Truncate(24 * time.Hour)
		deadline := today.AddDate(0, 0, days)
		for _, u := range scanUserAlerts(db) {
			if u.isActive == 0 {
				continue
			}
			if u.expiry == "" {
				continue
			}
			exp, err := time.Parse("2006-01-02", u.expiry[:min(10, len(u.expiry))])
			if err != nil || exp.Before(today) || exp.After(deadline) {
				continue
			}
			left := int(exp.Sub(today).Hours() / 24)
			items = append(items, map[string]any{
				"id": "expiry:" + firstNonEmpty(u.uuid, u.name), "type": "threshold_expiry",
				"level": "warning", "target": u.name,
				"title": fmt.Sprintf("%s expires in %d day(s)", u.name, left),
			})
		}
	}

	if s.alertUsageEnabled {
		limit := clamp(s.alertUsagePct, 1, 100)
		for _, u := range scanUserAlerts(db) {
			if u.isActive == 0 || u.total == nil || *u.total == 0 {
				continue
			}
			pct := float64(derefInt(u.used)) / float64(*u.total) * 100
			if pct < float64(limit) {
				continue
			}
			level := "warning"
			if pct >= 100 {
				level = "danger"
			}
			items = append(items, map[string]any{
				"id": "usage:" + firstNonEmpty(u.uuid, u.name), "type": "threshold_usage",
				"level": level, "target": u.name,
				"title": fmt.Sprintf("%s at %d%% of quota (warn limit %d%%)", u.name, bankerRound(pct), limit),
			})
		}
	}

	if s.alertCPUEnabled {
		limit := clamp(s.alertCPUPct, 1, 100)
		for _, n := range latestNodeCPU(db) {
			if n.cpu < float64(limit) {
				continue
			}
			items = append(items, map[string]any{
				"id": fmt.Sprintf("cpu:%d", n.id), "type": "threshold_cpu",
				"level": "warning", "target": n.name,
				"title": fmt.Sprintf("Node %s CPU at %d%% (warn limit %d%%)", n.name, bankerRound(n.cpu), limit),
			})
		}
	}
	return items
}

func (h *Handler) collectNow(w http.ResponseWriter, r *http.Request) {
	CollectMetrics(h.Svc.DB())
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Metrics snapshot collected"})
}

// --- metrics (observability/metrics.py) ---

// metricsTables is the DDL the collector/history need at runtime;
// migrations own it, this is the idempotent mirror.
var metricsTables = []string{
	`CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT)`,
	`CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)`,
	`CREATE TABLE IF NOT EXISTS node_health_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, node_id INTEGER, node_name TEXT, cpu REAL, memory REAL, live_count INTEGER, latency_ms REAL, reachable INTEGER NOT NULL DEFAULT 0)`,
	`CREATE INDEX IF NOT EXISTS idx_node_health_ts ON node_health_snapshots(ts)`,
	`CREATE TABLE IF NOT EXISTS traffic_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, total_used REAL NOT NULL, active_connections INTEGER NOT NULL, online_users INTEGER NOT NULL, active_users INTEGER NOT NULL, total_users INTEGER NOT NULL)`,
	`CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)`,
	`CREATE TABLE IF NOT EXISTS security_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, auth_errors INTEGER NOT NULL, rejects INTEGER NOT NULL, stale_markers INTEGER NOT NULL, offline_nodes INTEGER NOT NULL, full_users INTEGER NOT NULL, inactive_users INTEGER NOT NULL)`,
	`CREATE INDEX IF NOT EXISTS idx_security_snapshots_ts ON security_snapshots(ts)`,
	`CREATE TABLE IF NOT EXISTS user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day))`,
	`CREATE INDEX IF NOT EXISTS idx_user_traffic_day ON user_traffic_daily(day)`,
	`CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`,
	`CREATE TABLE IF NOT EXISTS traffic_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id INTEGER NOT NULL, node_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, delta_bytes INTEGER NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}', UNIQUE (user_id, ts, kind, node_id))`,
	`CREATE INDEX IF NOT EXISTS idx_traffic_ledger_user_ts ON traffic_ledger(user_id, ts)`,
	`CREATE TABLE IF NOT EXISTS settings_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL DEFAULT 0)`,
}

var tablesReady bool

// EnsureExtraTables creates the observability/billing tables once per process.
func EnsureExtraTables(db *sql.DB) {
	if tablesReady {
		return
	}
	for _, ddl := range metricsTables {
		_, _ = db.Exec(ddl)
	}
	tablesReady = true
}

// history mirrors metrics.history.
func (h *Handler) metricsHistory(w http.ResponseWriter, r *http.Request) {
	hours := intQuery(r, "hours", 24)
	EnsureExtraTables(h.Svc.DB())
	data := history(h.Svc.DB(), hours)
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Metrics history", Data: data})
}

func history(db *sql.DB, hours int) map[string]any {
	EnsureExtraTables(db)
	hours = max(1, min(hours, 24*30))
	cutoff := nowSecs() - float64(hours)*3600

	traffic := []map[string]any{}
	if rows, err := db.Query(`SELECT ts, total_used, active_connections, online_users, active_users, total_users FROM traffic_snapshots WHERE ts >= ? ORDER BY ts ASC`, cutoff); err == nil {
		for rows.Next() {
			var ts, totalUsed float64
			var ac, ou, au, tu int64
			if rows.Scan(&ts, &totalUsed, &ac, &ou, &au, &tu) == nil {
				traffic = append(traffic, map[string]any{
					"ts": ts, "total_used": totalUsed, "active_connections": ac,
					"online_users": ou, "active_users": au, "total_users": tu,
				})
			}
		}
		rows.Close()
	}

	security := []map[string]any{}
	if rows, err := db.Query(`SELECT ts, auth_errors, rejects, stale_markers, offline_nodes, full_users, inactive_users FROM security_snapshots WHERE ts >= ? ORDER BY ts ASC`, cutoff); err == nil {
		for rows.Next() {
			var ts float64
			var ae, rj, sm, of, fu, iu int64
			if rows.Scan(&ts, &ae, &rj, &sm, &of, &fu, &iu) == nil {
				security = append(security, map[string]any{
					"ts": ts, "auth_errors": ae, "rejects": rj, "stale_markers": sm,
					"offline_nodes": of, "full_users": fu, "inactive_users": iu,
				})
			}
		}
		rows.Close()
	}

	nodes := []map[string]any{}
	if rows, err := db.Query(`SELECT ts, node_id, node_name, cpu, memory, live_count, latency_ms, reachable FROM node_health_snapshots WHERE ts >= ? ORDER BY ts ASC`, cutoff); err == nil {
		for rows.Next() {
			var ts, cpu, mem, latency float64
			var nodeID, liveCount, reachable int64
			var nodeName sql.NullString
			if rows.Scan(&ts, &nodeID, &nodeName, &cpu, &mem, &liveCount, &latency, &reachable) == nil {
				nodes = append(nodes, map[string]any{
					"ts": ts, "node_id": nodeID, "node_name": nullStr(nodeName), "cpu": cpu,
					"memory": mem, "live_count": liveCount, "latency_ms": latency, "reachable": reachable != 0,
				})
			}
		}
		rows.Close()
	}

	return map[string]any{"traffic": traffic, "security": security, "nodes": nodes}
}

// CollectMetrics mirrors metrics.collect_metrics (synchronous in Go).
func CollectMetrics(db *sql.DB) {
	EnsureExtraTables(db)
	now := nowSecs()

	type userRow struct {
		name      string
		isActive  int64
		used      int64
		maxLogins int64
	}
	users := []userRow{}
	if rows, err := db.Query(`SELECT name, is_active, COALESCE(used,0), COALESCE(max_logins,0) FROM users`); err == nil {
		for rows.Next() {
			var u userRow
			if rows.Scan(&u.name, &u.isActive, &u.used, &u.maxLogins) == nil {
				users = append(users, u)
			}
		}
		rows.Close()
	}

	idToName := map[string]string{}
	nodeRows := []map[string]any{}
	sessionsByNode := []map[string]any{}
	if nrows, err := db.Query(`SELECT id FROM nodes WHERE status = 1`); err == nil {
		ids := []int64{}
		for nrows.Next() {
			var id int64
			if nrows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		nrows.Close()
		pid := node.PanelIDFor(db)
		for _, id := range ids {
			n := node.GetNodeByID(db, id)
			if n == nil {
				continue
			}
			row, sessions := nodeSnapshot(n, pid)
			nodeRows = append(nodeRows, row)
			sessionsByNode = append(sessionsByNode, sessions)
		}
	}
	if rows, err := db.Query(`SELECT id, name FROM users`); err == nil {
		for rows.Next() {
			var id int64
			var name string
			if rows.Scan(&id, &name) == nil {
				idToName[strconv.FormatInt(id, 10)] = name
			}
		}
		rows.Close()
	}

	checkNodeAlerts(db, nodeRows, readSettings(db).notifyNodeDown)
	checkThresholdAlerts(db)

	var activeConnections, authErrors, rejects, staleMarkers, offlineNodes int64
	for _, r := range nodeRows {
		activeConnections += toI64(r["live_count"])
		authErrors += toI64(r["auth_errors"])
		rejects += toI64(r["rejects"])
		staleMarkers += toI64(r["stale_markers"])
		if toI64(r["reachable"]) == 0 {
			offlineNodes++
		}
	}
	activeUsers := int64(0)
	var totalUsed float64
	for _, u := range users {
		if u.isActive != 0 {
			activeUsers++
		}
		totalUsed += float64(u.used)
	}
	inactiveUsers := int64(len(users)) - activeUsers

	// last_online + full-user count from the per-user live connection counts.
	activeCounts := map[string]int{}
	for _, sessions := range sessionsByNode {
		live, _ := sessions["live_sessions"].([]any)
		for _, item := range live {
			sess, _ := item.(map[string]any)
			cn, _ := sess["common_name"].(string)
			username := cn
			if mapped, ok := idToName[cn]; ok {
				username = mapped
			}
			activeCounts[username]++
		}
	}
	fullUsers := int64(0)
	for _, u := range users {
		count := activeCounts[u.name]
		if count > 0 {
			_, _ = db.Exec(`UPDATE users SET last_online = ? WHERE name = ?`, time.Now().UTC().Format("2006-01-02 15:04:05.000000"), u.name)
		}
		if u.maxLogins > 0 && int64(count) >= u.maxLogins {
			fullUsers++
		}
	}

	for _, row := range nodeRows {
		_, _ = db.Exec(`INSERT INTO node_health_snapshots (ts, node_id, node_name, cpu, memory, live_count, latency_ms, reachable) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
			now, row["node_id"], row["node_name"], row["cpu"], row["memory"], row["live_count"], row["latency_ms"], row["reachable"])
	}
	_, _ = db.Exec(`INSERT INTO traffic_snapshots (ts, total_used, active_connections, online_users, active_users, total_users) VALUES (?, ?, ?, ?, ?, ?)`,
		now, totalUsed, activeConnections, activeConnections, activeUsers, len(users))
	_, _ = db.Exec(`INSERT INTO security_snapshots (ts, auth_errors, rejects, stale_markers, offline_nodes, full_users, inactive_users) VALUES (?, ?, ?, ?, ?, ?, ?)`,
		now, authErrors, rejects, staleMarkers, offlineNodes, fullUsers, inactiveUsers)

	cutoff := now - 30*24*3600
	for _, table := range []string{"node_health_snapshots", "traffic_snapshots", "security_snapshots"} {
		_, _ = db.Exec(`DELETE FROM `+table+` WHERE ts < ?`, cutoff)
	}
}

// nodeSnapshot probes one node for info + sessions (metrics._node_snapshot).
func nodeSnapshot(n *node.Node, pid string) (map[string]any, map[string]any) {
	start := time.Now()
	info := node.NodeClient(n, pid).GetNodeInfo()
	sessions := node.NodeClient(n, pid).GetSessions("", 8, 0)
	latency := round1(float64(time.Since(start).Microseconds()) / 1000.0)
	if info == nil {
		info = map[string]any{}
	}
	if sessions == nil {
		sessions = map[string]any{}
	}
	reachable := len(info) > 0
	row := map[string]any{
		"node_id": n.ID, "node_name": n.Name,
		"cpu": f64(info["cpu_usage"]), "memory": f64(info["memory_usage"]),
		"live_count": toI64(sessions["live_count"]), "latency_ms": latency,
		"reachable": boolInt(reachable), "auth_errors": toI64(sessions["auth_errors"]),
		"rejects": toI64(sessions["rejects"]), "stale_markers": toI64(sessions["stale_marker_count"]),
	}
	return row, sessions
}

// --- collector (live.collect_live_snapshot) ---

const (
	lowResourcePollSeconds = 30.0
	graceSeconds           = 20.0
)

func idlePollSeconds() float64 { return envFloat("OVMANAGER_LIVE_IDLE_POLL_SECONDS", 300) }

// PollSeconds mirrors live.poll_seconds.
func PollSeconds() float64 {
	if v := os.Getenv("OVMANAGER_LIVE_POLL_SECONDS"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return lowResourcePollSeconds // ponytail: low_resource flag not re-read here
}

// CollectLiveSnapshot polls every active node and refreshes the snapshot.
func CollectLiveSnapshot(db *sql.DB) {
	if !DefaultBus.HasSubscribers() && SnapshotFresh() {
		return
	}
	cap := SnapshotMaxNodes
	if v := kvValue(db, SnapshotMaxNodesKey); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cap = n
		}
	}

	ids := []int64{}
	if rows, err := db.Query(`SELECT id FROM nodes WHERE status = 1`); err == nil {
		for rows.Next() {
			var id int64
			if rows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		rows.Close()
	}
	idToName := map[string]string{}
	if rows, err := db.Query(`SELECT id, name FROM users`); err == nil {
		for rows.Next() {
			var id int64
			var name string
			if rows.Scan(&id, &name) == nil {
				idToName[strconv.FormatInt(id, 10)] = name
			}
		}
		rows.Close()
	}
	pid := node.PanelIDFor(db)

	if len(ids) == 0 {
		_, nodesChanged := updateSnapshot(map[string]int{}, map[string]bool{}, cap)
		if nodesChanged {
			Publish("nodes", KV{"op", "snapshot"})
		}
		return
	}

	counts := map[string]int{}
	online := map[string]bool{}
	for _, id := range ids {
		n := node.GetNodeByID(db, id)
		if n == nil {
			continue
		}
		data := node.NodeClient(n, pid).GetSessions("", 1, node.ProbeTimeout(n))
		if len(data) == 0 {
			online[n.Name] = false
			continue
		}
		online[n.Name] = true
		live, _ := data["live_sessions"].([]any)
		for _, item := range live {
			sess, _ := item.(map[string]any)
			cn, _ := sess["common_name"].(string)
			username := cn
			if mapped, ok := idToName[cn]; ok {
				username = mapped
			}
			if username != "" {
				counts[username]++
			}
		}
	}
	online = applyGrace(online, NodeOnline(), time.Since(procStart).Seconds())
	countsChanged, nodesChanged := updateSnapshot(counts, online, cap)
	if nodesChanged {
		Publish("nodes", KV{"op", "status"})
	}
	if countsChanged {
		Publish("users", KV{"op", "connections"})
	}
}

// applyGrace holds a node that just went down as up (live._apply_grace).
func applyGrace(online, prev map[string]bool, now float64) map[string]bool {
	nodeAlerts.mu.Lock()
	defer nodeAlerts.mu.Unlock()
	names := map[string]bool{}
	for k := range prev {
		names[k] = true
	}
	for k := range online {
		names[k] = true
	}
	for name := range names {
		if online[name] {
			delete(nodeAlerts.graceUntil, name)
			online[name] = true
			continue
		}
		until, ok := nodeAlerts.graceUntil[name]
		if !ok && prev[name] {
			until = now + graceSeconds
			nodeAlerts.graceUntil[name] = until
		}
		if until != 0 && now >= until {
			delete(nodeAlerts.graceUntil, name)
			online[name] = false
		} else {
			online[name] = until != 0
		}
	}
	return online
}

// --- audit (observability/audit.py) ---

// RecordEvent writes one system event row (audit.record_event).
func RecordEvent(db *sql.DB, kind, severity, message string, meta map[string]any) {
	if meta == nil {
		meta = map[string]any{}
	}
	payload := map[string]any{"severity": severity, "message": message, "meta": meta}
	detail, _ := json.Marshal(payload)
	var target any
	if t, ok := meta["target"].(string); ok && t != "" {
		target = t
	}
	_, _ = db.Exec(`INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (?, 'system', ?, ?, ?)`,
		nowSecs(), kind, target, string(detail))
}

// lastEventMeta returns the meta of the newest record_event row for kind.
func lastEventMeta(db *sql.DB, kind string) map[string]any {
	var detail sql.NullString
	err := db.QueryRow(`SELECT detail FROM audit_logs WHERE action = ? AND actor = 'system' ORDER BY id DESC LIMIT 1`, kind).Scan(&detail)
	if err != nil || !detail.Valid || detail.String == "" {
		return nil
	}
	var payload map[string]any
	if json.Unmarshal([]byte(detail.String), &payload) != nil {
		return nil
	}
	meta, _ := payload["meta"].(map[string]any)
	return meta
}

// PromoteEvents delivers enrolled events to Telegram once each; returns the
// number sent. Exported for the health overview and panel alert routes.
func PromoteEvents(db *sql.DB, send func(string) bool) int { return promoteEvents(db, send) }

// promoteEvents delivers enrolled audit events to Telegram, once each.
func promoteEvents(db *sql.DB, send func(string) bool) int {
	delivered := map[string]bool{}
	if rows, err := db.Query(`SELECT subscription, event_key FROM delivered`); err == nil {
		for rows.Next() {
			var s, k string
			if rows.Scan(&s, &k) == nil {
				delivered[s+"\x00"+k] = true
			}
		}
		rows.Close()
	}
	rows, err := db.Query(`SELECT action, detail FROM audit_logs WHERE actor = 'system' ORDER BY id ASC`)
	if err != nil {
		return 0
	}
	type ev struct{ action, detail string }
	events := []ev{}
	for rows.Next() {
		var e ev
		if rows.Scan(&e.action, &e.detail) == nil {
			events = append(events, e)
		}
	}
	rows.Close()

	sent := 0
	for _, e := range events {
		var payload map[string]any
		if json.Unmarshal([]byte(e.detail), &payload) != nil {
			continue
		}
		meta, _ := payload["meta"].(map[string]any)
		key, _ := meta["event_key"].(string)
		if key == "" || delivered[e.action+"\x00"+key] {
			continue
		}
		message, _ := payload["message"].(string)
		if message == "" {
			message = e.action
		}
		if !send(message) {
			continue
		}
		_, _ = db.Exec(`INSERT OR IGNORE INTO delivered (subscription, event_key, ts) VALUES (?, ?, ?)`, e.action, key, nowSecs())
		delivered[e.action+"\x00"+key] = true
		sent++
	}
	return sent
}

// checkThresholdAlerts mirrors thresholds.check_threshold_alerts.
func checkThresholdAlerts(db *sql.DB) int {
	groups := map[string][]map[string]any{}
	order := []string{}
	for _, item := range thresholdItems(db) {
		t, _ := item["type"].(string)
		if _, seen := groups[t]; !seen {
			order = append(order, t)
		}
		groups[t] = append(groups[t], item)
	}
	kinds := append([]string{}, activeKinds...)
	for _, k := range order {
		found := false
		for _, a := range kinds {
			if a == k {
				found = true
			}
		}
		if !found {
			kinds = append(kinds, k)
		}
	}
	for _, kind := range kinds {
		group := groups[kind]
		signature := signatureOf(group)
		last := lastEventMeta(db, kind)
		lastSignature, _ := last["signature"].(string)
		if signature != "" {
			if lastSignature == signature {
				continue
			}
			level := "warning"
			for _, item := range group {
				if item["level"] == "danger" {
					level = "error"
				}
			}
			var target any
			if len(group) == 1 {
				target = group[0]["target"]
			}
			RecordEvent(db, kind, level, messageOf(group), map[string]any{
				"event_key": newEventKey(), "signature": signature, "target": target,
			})
		} else if lastSignature != "" {
			RecordEvent(db, kind, "info", kind+" condition cleared", map[string]any{"signature": ""})
		}
	}
	return promoteEvents(db, func(text string) bool { return sendTelegram(db, text) })
}

func signatureOf(group []map[string]any) string {
	if len(group) == 0 {
		return ""
	}
	parts := make([]string, len(group))
	for i, item := range group {
		parts[i] = fmt.Sprintf("%v:%v", item["id"], item["level"])
	}
	sort.Strings(parts)
	return strings.Join(parts, "|")
}

// messageOf mirrors thresholds._message.
func messageOf(group []map[string]any) string {
	titles := make([]string, len(group))
	for i, item := range group {
		titles[i], _ = item["title"].(string)
	}
	shown := titles
	if len(shown) > 10 {
		shown = shown[:10]
	}
	body := strings.Join(shown, "; ")
	if extra := len(titles) - len(shown); extra > 0 {
		body += fmt.Sprintf(" (+%d more)", extra)
	}
	return "Threshold alert: " + body
}

// --- node alerts (observability/node_alerts.py) ---

const downAlertCooldownSeconds = 30 * 60

// nodeAlerts owns every package-level live/node alert map. CollectMetrics is
// reachable concurrently from the worker tick and POST /metrics/collect, so
// each map access takes the mutex. graceUntil lives here too because the
// manual collect path can race the live worker.
var nodeAlerts = struct {
	mu             sync.Mutex
	nodeState      map[int64]bool
	lastDownAlert  map[int64]float64
	alertedDownSet map[int64]bool
	graceUntil     map[string]float64
}{
	nodeState:      map[int64]bool{},
	lastDownAlert:  map[int64]float64{},
	alertedDownSet: map[int64]bool{},
	graceUntil:     map[string]float64{},
}

// checkNodeAlerts mirrors node_alerts.check_node_alerts.
func checkNodeAlerts(db *sql.DB, rows []map[string]any, notify bool) int {
	sent := 0
	ts := nowSecs()
	for _, row := range rows {
		nodeID := toI64(row["node_id"])
		if nodeID == 0 {
			continue
		}
		name, _ := row["node_name"].(string)
		if name == "" {
			name = fmt.Sprintf("node-%d", nodeID)
		}
		reachable := boolOf(row["reachable"])

		nodeAlerts.mu.Lock()
		prev, seen := nodeAlerts.nodeState[nodeID]
		nodeAlerts.nodeState[nodeID] = reachable
		alertedDown := nodeAlerts.alertedDownSet[nodeID]
		lastDown := nodeAlerts.lastDownAlert[nodeID]
		nodeAlerts.mu.Unlock()

		if !seen {
			continue
		}
		if prev != reachable {
			kind := "node.up"
			sev := "info"
			msg := "🟢 Node " + name + " is back online."
			if !reachable {
				kind, sev, msg = "node.down", "error", "🔴 Node "+name+" is unreachable."
			}
			RecordEvent(db, kind, sev, msg, map[string]any{"node_id": nodeID, "target": name})
		}
		if !reachable {
			if alertedDown || !notify {
				continue
			}
			if ts-lastDown < downAlertCooldownSeconds {
				continue
			}
			if sendTelegram(db, "🔴 Node "+name+" is unreachable.") {
				nodeAlerts.mu.Lock()
				nodeAlerts.lastDownAlert[nodeID] = ts
				nodeAlerts.alertedDownSet[nodeID] = true
				nodeAlerts.mu.Unlock()
				sent++
			}
		} else if alertedDown {
			nodeAlerts.mu.Lock()
			delete(nodeAlerts.alertedDownSet, nodeID)
			nodeAlerts.mu.Unlock()
			if notify && sendTelegram(db, "🟢 Node "+name+" is back online.") {
				sent++
			}
		}
	}
	return sent
}

// --- notifier (observability/notifier.py) ---

// SendTelegram is the exported notifier for the panel's alert test and the
// health-overview promoter.
func SendTelegram(db *sql.DB, text string) bool { return sendTelegram(db, text) }

// sendTelegram sends one message through the notify package (the shared
// stdlib transport); false when the bot is unconfigured or the transport
// fails (notifier.send_telegram). Plain text — no HTML parse mode.
func sendTelegram(db *sql.DB, text string) bool {
	if db == nil {
		return false
	}
	var enabled sql.NullInt64
	var ownerID sql.NullInt64
	var token sql.NullString
	err := db.QueryRow(`SELECT bot_enabled, owner_telegram_id, bot_token FROM settings LIMIT 1`).
		Scan(&enabled, &ownerID, &token)
	if err != nil || !enabled.Valid || enabled.Int64 == 0 || !ownerID.Valid || !token.Valid || token.String == "" {
		return false
	}
	tok := token.String
	if strings.HasPrefix(tok, "enc:") {
		return false // legacy encrypted token fails closed
	}
	return notify.SendMessage(tok, strconv.FormatInt(ownerID.Int64, 10), text) == nil
}

// nilDB is unused; kept out — RecordEvent always takes a live handle.

// --- helpers ---

type settingsRow struct {
	notifyExpiry      bool
	notifyNodeDown    bool
	alertDaysLeft     int
	alertUsageEnabled bool
	alertUsagePct     int
	alertCPUEnabled   bool
	alertCPUPct       int
}

func readSettings(db *sql.DB) settingsRow {
	s := settingsRow{
		notifyExpiry: true, notifyNodeDown: true, alertDaysLeft: defaultDaysLeft,
		alertUsageEnabled: true, alertUsagePct: defaultUsagePct,
		alertCPUEnabled: true, alertCPUPct: defaultCPUPct,
	}
	var ne, nnd, aue, ace sql.NullInt64
	var days, upct, cpct sql.NullInt64
	err := db.QueryRow(`SELECT notify_expiry, notify_node_down, alert_days_left, alert_usage_enabled, alert_usage_pct, alert_cpu_enabled, alert_cpu_pct FROM settings LIMIT 1`).
		Scan(&ne, &nnd, &days, &aue, &upct, &ace, &cpct)
	if err != nil {
		return s
	}
	s.notifyExpiry = ne.Valid && ne.Int64 != 0
	s.notifyNodeDown = !nnd.Valid || nnd.Int64 != 0
	s.alertDaysLeft = clamp(intOf(days), 0, 365)
	s.alertUsageEnabled = !aue.Valid || aue.Int64 != 0
	s.alertUsagePct = clamp(intOf(upct), 1, 100)
	s.alertCPUEnabled = !ace.Valid || ace.Int64 != 0
	s.alertCPUPct = clamp(intOf(cpct), 1, 100)
	return s
}

type userAlert struct {
	uuid     string
	name     string
	isActive int64
	expiry   string
	total    *int64
	used     *int64
}

func scanUserAlerts(db *sql.DB) []userAlert {
	rows, err := db.Query(`SELECT COALESCE(uuid,''), name, COALESCE(is_active,0), COALESCE(expiry_date,''), total, used FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []userAlert
	for rows.Next() {
		var u userAlert
		var expiry sql.NullString
		if rows.Scan(&u.uuid, &u.name, &u.isActive, &expiry, &u.total, &u.used) == nil {
			u.expiry = expiry.String
			out = append(out, u)
		}
	}
	return out
}

type nodeCPU struct {
	id   int64
	name string
	cpu  float64
}

func latestNodeCPU(db *sql.DB) []nodeCPU {
	var exists int64
	if db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='node_health_snapshots'`).Scan(&exists) != nil || exists == 0 {
		return nil
	}
	rows, err := db.Query(`SELECT node_id, node_name, cpu FROM node_health_snapshots WHERE id IN (SELECT MAX(id) FROM node_health_snapshots GROUP BY node_id)`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []nodeCPU
	for rows.Next() {
		var id int64
		var name sql.NullString
		var cpu sql.NullFloat64
		if rows.Scan(&id, &name, &cpu) == nil {
			n := name.String
			if n == "" {
				n = fmt.Sprintf("node-%d", id)
			}
			out = append(out, nodeCPU{id: id, name: n, cpu: cpu.Float64})
		}
	}
	return out
}

func kvValue(db *sql.DB, key string) string {
	var v sql.NullString
	if db.QueryRow(`SELECT value FROM settings_kv WHERE key = ?`, key).Scan(&v) != nil {
		return ""
	}
	return v.String
}

// bankerRound is banker's rounding, which Go's math.Round is not.
func bankerRound(f float64) int {
	floor := math.Floor(f)
	diff := f - floor
	if diff > 0.5 {
		return int(floor) + 1
	}
	if diff < 0.5 {
		return int(floor)
	}
	// exactly .5 → round to even
	if int64(floor)%2 == 0 {
		return int(floor)
	}
	return int(floor) + 1
}

// round1 is round(x, 1).
func round1(f float64) float64 {
	return math.Round(f*10) / 10
}

func clamp(v, low, high int) int {
	if v < low {
		return low
	}
	if v > high {
		return high
	}
	return v
}

func intQuery(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

func newEventKey() string {
	buf := make([]byte, 16)
	_, _ = rand.Read(buf)
	return hex.EncodeToString(buf)
}

func escapeLike(s string) string {
	s = strings.ReplaceAll(s, `\`, `\\`)
	s = strings.ReplaceAll(s, "%", `\%`)
	return strings.ReplaceAll(s, "_", `\_`)
}

func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func nullStr(v sql.NullString) any {
	if !v.Valid || v.String == "" {
		return nil
	}
	return v.String
}

func derefInt(v *int64) int64 {
	if v == nil {
		return 0
	}
	return *v
}

func intOf(v sql.NullInt64) int {
	if !v.Valid {
		return 0
	}
	return int(v.Int64)
}

func f64(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int:
		return float64(n)
	case int64:
		return float64(n)
	}
	return 0
}

func toI64(v any) int64 {
	switch n := v.(type) {
	case float64:
		return int64(n)
	case int:
		return int64(n)
	case int64:
		return n
	}
	return 0
}

func boolOf(v any) bool {
	switch n := v.(type) {
	case bool:
		return n
	case int:
		return n != 0
	case int64:
		return n != 0
	case float64:
		return n != 0
	}
	return false
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
