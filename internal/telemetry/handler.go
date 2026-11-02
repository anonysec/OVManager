package telemetry

import (
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/billing"
	"github.com/anonysec/OVManager/go/internal/node"
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
	mux.HandleFunc("GET /live/stream", h.Svc.RequireUser(StreamHandler(h.Svc, DefaultBus)))
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
		_ = rows.Close()
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
	`CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor, id)`,
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

var tablesReady sync.Once

// EnsureExtraTables creates the observability/billing tables once per process.
func EnsureExtraTables(db *sql.DB) {
	tablesReady.Do(func() {
		for _, ddl := range metricsTables {
			_, _ = db.Exec(ddl)
		}
	})
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
		_ = rows.Close()
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
		_ = rows.Close()
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
		_ = rows.Close()
	}

	return map[string]any{"traffic": traffic, "security": security, "nodes": nodes}
}

// metricsEvery is the collector's own cadence. Configurable via
// OVM_METRICS_INTERVAL_SECONDS (default 300). shortcut: 5 min bounds the node
// probes and the history tables (288 samples/day); a node-down alert lands up
// to 5 min late. Drop to 1 min when alert latency matters more than probe load.
func metricsEvery() time.Duration {
	if v := envOrFileTelemetry("OVM_METRICS_INTERVAL_SECONDS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return time.Duration(n) * time.Second
		}
	}
	return 5 * time.Minute
}

var (
	metricsLastMu sync.Mutex
	metricsLastTS time.Time
)

// metricsDue reports whether a collect is due at now, and claims the window.
func metricsDue(now time.Time) bool {
	metricsLastMu.Lock()
	defer metricsLastMu.Unlock()
	if metricsLastTS.IsZero() || now.Sub(metricsLastTS) >= metricsEvery() {
		metricsLastTS = now
		return true
	}
	return false
}

// CollectMetricsIfDue runs one metrics pass at most every metricsEvery and
// reports whether it did. It is the only scheduled entry point: the panel's
// live and traffic workers must not each run a full collect.
func CollectMetricsIfDue(db *sql.DB) bool {
	if !metricsDue(time.Now()) {
		return false
	}
	CollectMetrics(db)
	return true
}

// CollectMetrics mirrors metrics.collect_metrics (synchronous in Go).
// touchLastOnline stamps last_online for a batch of usernames in one
// statement — the collect path runs per live session, and one Exec per
// session is a write storm on SQLite's single writer.
func touchLastOnline(db *sql.DB, names []string, stamp string) {
	if len(names) == 0 {
		return
	}
	placeholders := strings.TrimSuffix(strings.Repeat("?,", len(names)), ",")
	args := make([]any, 0, len(names)+1)
	args = append(args, stamp)
	for _, n := range names {
		args = append(args, n)
	}
	_, _ = db.Exec(`UPDATE users SET last_online = ? WHERE name IN (`+placeholders+`)`, args...) // #nosec // placeholders only
}

func CollectMetrics(db *sql.DB) {
	EnsureExtraTables(db)
	now := nowSecs()

	type userRow struct {
		id        int64
		name      string
		isActive  int64
		used      int64
		maxLogins int64
	}
	users := []userRow{}
	if rows, err := db.Query(`SELECT id, name, is_active, COALESCE(used,0), COALESCE(max_logins,0) FROM users`); err == nil {
		for rows.Next() {
			var u userRow
			if rows.Scan(&u.id, &u.name, &u.isActive, &u.used, &u.maxLogins) == nil {
				users = append(users, u)
			}
		}
		_ = rows.Close()
	}

	idToName := make(map[string]string, len(users))
	known := make(map[string]bool, len(users))
	for _, u := range users {
		idToName[strconv.FormatInt(u.id, 10)] = u.name
		known[u.name] = true
	}
	nodeRows := []map[string]any{}
	sessionsByNode := []snapshotPair{}
	if nrows, err := db.Query(`SELECT id FROM nodes WHERE status = 1`); err == nil {
		ids := []int64{}
		for nrows.Next() {
			var id int64
			if nrows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		_ = nrows.Close()
		pid := node.PanelIDFor(db)
		nodes := make([]*node.Node, 0, len(ids))
		for _, id := range ids {
			if n := node.GetNodeByID(db, id); n != nil {
				nodes = append(nodes, n)
			}
		}
		calls := make([]func() any, 0, len(nodes))
		for _, n := range nodes {
			n := n
			calls = append(calls, func() any {
				row, sessions := nodeSnapshot(n, pid)
				return snapshotPair{row: row, sessions: sessions, nodeName: n.Name}
			})
		}
		for _, res := range node.GatherNodes(calls, metricsFanoutDeadline) {
			if p, ok := res.(snapshotPair); ok {
				nodeRows = append(nodeRows, p.row)
				sessionsByNode = append(sessionsByNode, p)
			}
		}
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
	for _, snapshot := range sessionsByNode {
		live, ok := snapshot.sessions["live_sessions"].([]any)
		if !ok {
			continue
		}
		for _, item := range live {
			sess, ok := item.(map[string]any)
			if !ok {
				continue
			}
			cn, _ := sess["common_name"].(string)
			username := resolveSessionUsername(cn, snapshot.nodeName, idToName, known)
			if username != "" {
				activeCounts[username]++
			}
		}
	}
	fullUsers := int64(0)
	stamp := time.Now().UTC().Format("2006-01-02 15:04:05.000000")
	touched := make([]string, 0, len(users))
	for _, u := range users {
		count := activeCounts[u.name]
		if count > 0 {
			touched = append(touched, u.name)
		}
		if u.maxLogins > 0 && int64(count) >= u.maxLogins {
			fullUsers++
		}
	}
	touchLastOnline(db, touched, stamp)

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
		_, _ = db.Exec(`DELETE FROM `+table+` WHERE ts < ?`, cutoff) // #nosec // table from fixed list
	}
	// audit_logs grows forever otherwise: every login and user mutation writes
	// a row, and the only other caller of PruneAuditLogs is the manual cleanup.
	PruneAuditLogs(db, 90)
}

// nodeSnapshot probes one node for info + sessions (metrics._node_snapshot).
// snapshotPair carries nodeSnapshot's two return values through GatherNodes,
// which types every call result as any.
type snapshotPair struct {
	row      map[string]any
	sessions map[string]any
	nodeName string
}

// resolveSessionUsername normalizes the name-shaped and numeric common-name
// formats shared by the metrics and live-snapshot collectors.
func resolveSessionUsername(commonName, nodeName string, idToName map[string]string, known map[string]bool) string {
	return billing.ResolveSessionUsername(commonName, nodeName, idToName, known)
}

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

func idlePollSeconds() float64 { return envFloat("OVMANAGER_LIVE_IDLE_POLL_SECONDS", 300, true) }

// liveFanoutDeadline bounds one CollectLiveSnapshot fan-out. A var so tests can
// shrink it; production uses the shared request fan-out deadline.
var liveFanoutDeadline = node.RequestFanoutDeadline

// metricsFanoutDeadline bounds one CollectMetrics fan-out. A var so tests can
// shrink it; production uses the shared request fan-out deadline.
var metricsFanoutDeadline = node.RequestFanoutDeadline

// PollSeconds mirrors live.poll_seconds.
func PollSeconds() float64 {
	if v := envOrFileTelemetry("OVMANAGER_LIVE_POLL_SECONDS"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return lowResourcePollSeconds // note: low_resource flag not re-read here
}

// pollDue reports whether enough time has passed since the last poll to run
// another. The window is PollSeconds while a browser holds the live stream
// open, idlePollSeconds otherwise (design §5.2). now and LastPollTS are both
// monotonic seconds since start, so a caller's ticker and this gate agree.
func pollDue(now float64) bool {
	window := PollSeconds()
	if !DefaultBus.HasSubscribers() {
		window = idlePollSeconds()
	}
	last := LastPollTS()
	return last == 0 || now-last >= window
}

// CollectLiveSnapshot polls every active node and refreshes the snapshot.
func CollectLiveSnapshot(db *sql.DB) {
	if !pollDue(time.Since(procStart).Seconds()) {
		return
	}
	cap := SnapshotMaxNodes
	if v := kvValue(db, SnapshotMaxNodesKey); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cap = n
		}
	}

	ids := []int64{}
	nodesErr := error(nil)
	if rows, err := db.Query(`SELECT id FROM nodes WHERE status = 1`); err == nil {
		for rows.Next() {
			var id int64
			if rows.Scan(&id) == nil {
				ids = append(ids, id)
			}
		}
		_ = rows.Close()
	} else {
		nodesErr = err
	}
	idToName := map[string]string{}
	known := map[string]bool{}
	usersErr := error(nil)
	if rows, err := db.Query(`SELECT id, name FROM users`); err == nil {
		for rows.Next() {
			var id int64
			var name string
			if rows.Scan(&id, &name) == nil {
				idToName[strconv.FormatInt(id, 10)] = name
				known[name] = true
			}
		}
		_ = rows.Close()
	} else {
		usersErr = err
	}
	pid := node.PanelIDFor(db)

	// An empty result is otherwise silent; the counts make it diagnosable.
	if nodesErr != nil || usersErr != nil {
		log.Printf("telemetry: live snapshot: load failed (nodes=%d err=%v, users=%d err=%v)",
			len(ids), nodesErr, len(known), usersErr)
	}

	if len(ids) == 0 {
		_, nodesChanged := updateSnapshot(map[string]int{}, map[string]bool{}, cap)
		if nodesChanged {
			Publish("nodes", KV{"op", "snapshot"})
		}
		return
	}

	nodes := make([]*node.Node, 0, len(ids))
	for _, id := range ids {
		if n := node.GetNodeByID(db, id); n != nil {
			nodes = append(nodes, n)
		}
	}
	share := node.FairShareTimeout(liveFanoutDeadline, len(nodes), node.NodeFanoutLimit)
	calls := make([]func() any, len(nodes))
	for i, n := range nodes {
		n := n
		calls[i] = func() any {
			return node.NodeClient(n, pid).GetSessions("", 1, node.NodeTimeout(n, share))
		}
	}
	results := node.GatherNodes(calls, liveFanoutDeadline)

	counts := map[string]int{}
	online := map[string]bool{}
	touched := map[string]bool{}
	for i, n := range nodes {
		data, _ := results[i].(map[string]any)
		if len(data) == 0 {
			online[n.Name] = false
			continue
		}
		online[n.Name] = true
		live, ok := data["live_sessions"].([]any)
		if !ok {
			continue
		}
		for _, item := range live {
			sess, ok := item.(map[string]any)
			if !ok {
				continue
			}
			cn, _ := sess["common_name"].(string)
			username := resolveSessionUsername(cn, n.Name, idToName, known)
			if username != "" {
				counts[username]++
				touched[username] = true
			}
		}
	}
	names := make([]string, 0, len(touched))
	for u := range touched {
		names = append(names, u)
	}
	touchLastOnline(db, names, time.Now().UTC().Format("2006-01-02 15:04:05.000000"))
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
//
// The row is attributed to "system": it is a system event, not something a
// person did. An operation a person performed goes through audit.Record with
// the real username. The payload shape is identical either way, so the event
// promoter and the audit prune see the same rows.
