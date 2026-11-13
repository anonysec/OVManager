package telemetry

import (
	"database/sql"
	"fmt"
	"log"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/accounting"
	"github.com/anonysec/OVManager/internal/audit"
	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/node"
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
	owner := h.Svc.RequireUser
	mux.HandleFunc("GET /activity/", guard(h.activity))
	mux.HandleFunc("GET /metrics/history", owner(h.metricsHistory))
	mux.HandleFunc("POST /metrics/collect", owner(h.collectNow))
	mux.HandleFunc("GET /notifications/", guard(h.notifications))
	mux.HandleFunc("GET /live/stream", h.Svc.RequireUser(StreamHandler(h.Svc, DefaultBus)))
}

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
	_ = db
	return recentFrom(audit.ReadLines(), limit, actor, action)
}

// recentFrom walks the append-ordered trail from the end, so the page shows
// today's events rather than the oldest ones that fit the limit.
func recentFrom(lines []map[string]any, limit int, actor, action *string) []map[string]any {
	limit = clamp(limit, 1, 500)
	out := []map[string]any{}
	for i := len(lines) - 1; i >= 0; i-- {
		obj := lines[i]
		if actor != nil && fmt.Sprint(obj["actor"]) != *actor {
			continue
		}
		if action != nil && *action != "" {
			a, _ := obj["action"].(string)
			if !strings.HasPrefix(a, *action) {
				continue
			}
		}
		id, _ := obj["id"].(float64)
		ts, _ := obj["ts"].(float64)
		out = append(out, map[string]any{
			"id": int64(id), "ts": ts, "actor": obj["actor"],
			"action": obj["action"], "target": obj["target"],
			"detail": obj["detail"],
		})
		if len(out) >= limit {
			break
		}
	}
	return out
}

// INBOXTypes: threshold types that surface in the inbox (usage is Telegram-only).
var inboxTypes = map[string]bool{"threshold_expiry": true, "threshold_cpu": true}

func (h *Handler) notifications(w http.ResponseWriter, r *http.Request) {
	items := []map[string]any{}
	rows, err := h.Svc.DB().Query(`SELECT name, status FROM Node ORDER BY id`)
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

// metricsTables is the DDL the collector/history need at runtime;
// migrations own it, this is the idempotent mirror.
var metricsTables = []string{
	`CREATE TABLE IF NOT EXISTS Delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`,
}

var tablesReady sync.Once

// EnsureExtraTables creates the observability/accounting tables once per process.
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
	if rows, err := db.Query(`SELECT ts, total_used, active_connections FROM TrafficStat WHERE ts >= ? ORDER BY ts ASC`, cutoff); err == nil {
		for rows.Next() {
			var ts, totalUsed float64
			var ac int64
			if rows.Scan(&ts, &totalUsed, &ac) == nil {
				traffic = append(traffic, map[string]any{
					"ts": ts, "total_used": totalUsed, "active_connections": ac,
				})
			}
		}
		_ = rows.Close()
	}

	nodes := []map[string]any{}
	if rows, err := db.Query(`
		SELECT ns.ts, ns.node_id, n.name, ns.cpu, ns.memory, ns.live_count, ns.reachable
		FROM NodeStat ns
		JOIN Node n ON n.id = ns.node_id
		WHERE ns.ts >= ? ORDER BY ns.ts ASC
	`, cutoff); err == nil {
		for rows.Next() {
			var ts, cpu, mem float64
			var nodeID, liveCount, reachable int64
			var nodeName sql.NullString
			if rows.Scan(&ts, &nodeID, &nodeName, &cpu, &mem, &liveCount, &reachable) == nil {
				nodes = append(nodes, map[string]any{
					"ts": ts, "node_id": nodeID, "node_name": nullStr(nodeName),
					"cpu": cpu, "memory": mem, "live_count": liveCount, "reachable": reachable != 0,
				})
			}
		}
		_ = rows.Close()
	}

	return map[string]any{"traffic": traffic, "nodes": nodes}
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
	_, _ = db.Exec(`UPDATE User SET last_online = ? WHERE name IN (`+placeholders+`)`, args...) // #nosec // placeholders only
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
	if rows, err := db.Query(`SELECT id, name, is_active, COALESCE(used,0), COALESCE(max_logins,0) FROM User`); err == nil {
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
	if nrows, err := db.Query(`SELECT id FROM Node WHERE status = 1`); err == nil {
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
		if snapshot.sessions == nil {
			continue
		}
		for _, sess := range snapshot.sessions.LiveSessions {
			username := resolveSessionUsername(sess.CommonName, snapshot.nodeName, idToName, known)
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
		_, _ = db.Exec(`INSERT INTO TrafficStat (ts, total_used, active_connections) VALUES (?, ?, ?)`,
			now, totalUsed, activeConnections)
		_, _ = db.Exec(`INSERT INTO NodeStat (node_id, created_at, cpu, memory, live_count, reachable) VALUES (?, ?, ?, ?, ?, ?)`,
			row["node_id"], now, row["cpu"], row["memory"], row["live_count"], row["reachable"])
	}
	_ = totalUsed
	_ = activeConnections
	_ = activeUsers
	_ = authErrors
	_ = rejects
	_ = staleMarkers
	_ = offlineNodes
	_ = fullUsers
	_ = inactiveUsers
}

// nodeSnapshot probes one node for info + sessions (metrics._node_snapshot).
// snapshotPair carries nodeSnapshot's two return values through GatherNodes,
// which types every call result as any.
type snapshotPair struct {
	row      map[string]any
	sessions *node.SessionsResponse
	nodeName string
}

// resolveSessionUsername normalizes the name-shaped and numeric common-name
// formats shared by the metrics and live-snapshot collectors.
func resolveSessionUsername(commonName, nodeName string, idToName map[string]string, known map[string]bool) string {
	return accounting.ResolveSessionUsername(commonName, nodeName, idToName, known)
}

func nodeSnapshot(n *node.Node, pid string) (map[string]any, *node.SessionsResponse) {
	start := time.Now()
	info := node.NodeClient(n, pid).GetNodeInfo()
	sess, _ := node.NodeClient(n, pid).GetSessions("", 8, 0)
	latency := round1(float64(time.Since(start).Microseconds()) / 1000.0)
	if info == nil {
		info = map[string]any{}
	}
	reachable := len(info) > 0
	var liveCount, authErrors, rejects, staleMarkers int64
	if sess != nil {
		liveCount, authErrors, rejects, staleMarkers = int64(sess.LiveCount), int64(sess.AuthErrors), int64(sess.Rejects), int64(sess.StaleMarkerCount)
	}
	row := map[string]any{
		"node_id": n.ID, "node_name": n.Name,
		"cpu": f64(info["cpu_usage"]), "memory": f64(info["memory_usage"]),
		"live_count": liveCount, "latency_ms": latency,
		"reachable": boolInt(reachable), "auth_errors": authErrors,
		"rejects": rejects, "stale_markers": staleMarkers,
	}
	return row, sess
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
	// A poll owns the snapshot wholesale; anything a stream left behind is
	// superseded the moment the ticker runs again.
	resetPerNode()
	cap := SnapshotMaxNodes
	if v := kvValue(db); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cap = n
		}
	}

	ids := []int64{}
	nodesErr := error(nil)
	if rows, err := db.Query(`SELECT id FROM Node WHERE status = 1`); err == nil {
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
	if rows, err := db.Query(`SELECT id, name FROM User`); err == nil {
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
			s, _ := node.NodeClient(n, pid).GetSessions("", 1, node.NodeTimeout(n, share))
			return s
		}
	}
	results := node.GatherNodes(calls, liveFanoutDeadline)

	counts := map[string]int{}
	online := map[string]bool{}
	touched := map[string]bool{}
	for i, n := range nodes {
		sess, _ := results[i].(*node.SessionsResponse)
		if sess == nil {
			online[n.Name] = false
			continue
		}
		online[n.Name] = true
		for _, entry := range sess.LiveSessions {
			username := resolveSessionUsername(entry.CommonName, n.Name, idToName, known)
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

// ApplyNodeSessions folds ONE node's live sessions into the shared snapshot.
// It replaces that node's previous contribution (other nodes are untouched),
// stamps last_online for the users it saw, and publishes users/nodes exactly
// like the poll collector. usageTotals carries a display-only usage sample:
// it is published, never written to the database (Review Focus 4).
func ApplyNodeSessions(db *sql.DB, n *node.Node, sess *node.SessionsResponse, usageTotals map[string]uint64) error {
	if n == nil {
		return nil
	}
	if sess != nil {
		if err := applyNodeSessionState(db, n, sess); err != nil {
			return err
		}
	}
	if usageTotals != nil {
		usage := make(map[string]uint64, len(usageTotals))
		for name, bytes := range usageTotals {
			usage[name] = bytes
		}
		snap.mu.Lock()
		snap.byNodeUsage[n.Name] = usage
		snap.mu.Unlock()
		pairs := make([]KV, 0, len(usage))
		for name, bytes := range usage {
			pairs = append(pairs, KV{name, int64(bytes)}) // #nosec G115 -- usage is a byte counter that fits int64
		}
		sort.Slice(pairs, func(i, j int) bool { return pairs[i].Key < pairs[j].Key })
		Publish("users", KV{"op", "usage"}, KV{"usage", pairs})
	}
	applyNodeSnapshot()
	return nil
}

// sessionRejectActions are the reject verdicts the node's classifier emits
// for a refused connection (see the node's ovpn/events.go). A session event
// with any of these actions becomes a browser toast; the node may add new
// ones, and they simply stay silent until listed here.
var sessionRejectActions = map[string]bool{
	"disabled":      true,
	"fail_closed":   true,
	"mgmt_degraded": true,
	"global_check":  true,
	"global_policy": true,
	"other":         true,
	"check_failed":  true,
}

// rejectKey dedupes announceable reject rows: one hook line is one event.
func rejectKey(ev node.EventEntry) string {
	return ev.CN + "|" + strconv.FormatFloat(ev.TS, 'f', -1, 64) + "|" + ev.Action
}

// applyNodeSessionState replaces one node's per-user counts and publishes the
// session transitions the browser shows as toasts. The first snapshot after a
// stream starts is a silent baseline: it would otherwise replay every user
// already connected.
func applyNodeSessionState(db *sql.DB, n *node.Node, sess *node.SessionsResponse) error {
	idToName, known, err := snapshotUsers(db)
	if err != nil {
		return err
	}
	counts := map[string]int{}
	peer := map[string]string{}
	touched := map[string]bool{}
	for _, entry := range sess.LiveSessions {
		username := resolveSessionUsername(entry.CommonName, n.Name, idToName, known)
		if username == "" {
			continue
		}
		counts[username]++
		touched[username] = true
		if entry.Peer != "" {
			peer[username] = entry.Peer
		}
	}
	names := make([]string, 0, len(touched))
	for u := range touched {
		names = append(names, u)
	}
	touchLastOnline(db, names, time.Now().UTC().Format("2006-01-02 15:04:05.000000"))

	snap.mu.Lock()
	prev, hadBaseline := snap.byNode[n.Name]
	prevRejects := snap.byNodeRejects[n.Name]
	snap.byNode[n.Name] = counts
	snap.byNodeOnline[n.Name] = true
	seen := map[string]bool{}
	for _, ev := range sess.Events {
		if sessionRejectActions[ev.Action] {
			seen[rejectKey(ev)] = true
		}
	}
	snap.byNodeRejects[n.Name] = seen
	snap.mu.Unlock()

	if !hadBaseline {
		return nil
	}
	gone := make([]string, 0, len(prev))
	for name := range prev {
		if counts[name] == 0 {
			gone = append(gone, name)
		}
	}
	joined := make([]string, 0, len(counts))
	for name := range counts {
		if prev[name] == 0 {
			joined = append(joined, name)
		}
	}
	sort.Strings(gone)
	sort.Strings(joined)
	for _, name := range gone {
		Publish("users.session", KV{"op", "session"}, KV{"name", name}, KV{"action", "disconnect"})
	}
	for _, name := range joined {
		data := []KV{{"op", "session"}, {"name", name}, {"action", "connect"}}
		if ip := peer[name]; ip != "" {
			data = append(data, KV{"ip", ip})
		}
		Publish("users.session", data...)
	}
	for _, ev := range sess.Events {
		if !sessionRejectActions[ev.Action] || prevRejects[rejectKey(ev)] {
			continue
		}
		data := []KV{{"op", "session"}, {"name", ev.CN}, {"action", "reject"}, {"reason", ev.Reason}}
		if ev.Peer != "" {
			data = append(data, KV{"ip", ev.Peer})
		}
		Publish("users.session", data...)
	}
	return nil
}

// snapshotUsers loads the numeric-id and name lookup the session resolver
// needs. Shared by the stream apply path; the poll collector keeps its own
// inline load so its behavior stays byte-identical.
func snapshotUsers(db *sql.DB) (map[string]string, map[string]bool, error) {
	idToName := map[string]string{}
	known := map[string]bool{}
	rows, err := db.Query(`SELECT id, name FROM User`)
	if err != nil {
		return idToName, known, err
	}
	defer rows.Close()
	for rows.Next() {
		var id int64
		var name string
		if rows.Scan(&id, &name) == nil {
			idToName[strconv.FormatInt(id, 10)] = name
			known[name] = true
		}
	}
	return idToName, known, rows.Err()
}

// MarkNodeOffline flips one node offline through the same grace path the
// collector uses: its sessions stop counting at once, and the badge holds
// for the grace window exactly as a failed poll's would.
func MarkNodeOffline(nodeName string) {
	snap.mu.Lock()
	delete(snap.byNode, nodeName)
	snap.byNodeOnline[nodeName] = false
	snap.mu.Unlock()
	applyNodeSnapshot()
}

// applyNodeSnapshot merges every streaming node's contribution, applies the
// same grace window the collector uses, and publishes the same users/nodes
// events.
func applyNodeSnapshot() {
	counts := map[string]int{}
	online := map[string]bool{}
	usage := map[string]uint64{}
	snap.mu.Lock()
	for _, perUser := range snap.byNode {
		for name, n := range perUser {
			counts[name] += n
		}
	}
	for name, up := range snap.byNodeOnline {
		online[name] = up
	}
	for _, perUser := range snap.byNodeUsage {
		for name, bytes := range perUser {
			usage[name] += bytes
		}
	}
	capacity := snap.capacity
	snap.mu.Unlock()
	online = applyGrace(online, NodeOnline(), time.Since(procStart).Seconds())
	countsChanged, nodesChanged := updateSnapshot(counts, online, capacity)
	if nodesChanged {
		Publish("nodes", KV{"op", "status"})
	}
	if countsChanged {
		Publish("users", KV{"op", "connections"})
	}
	publishLivePayloads(counts, online, usage)
}

// publishLivePayloads carries the monitoring data itself, not an
// invalidation: the browser renders dots and usage straight from these maps,
// so a live frame causes no refetch. Both topics contain "." so the client
// never derives a ".changed" invalidation from them.
func publishLivePayloads(counts map[string]int, online map[string]bool, usage map[string]uint64) {
	userNames := make([]string, 0, len(counts))
	for name := range counts {
		userNames = append(userNames, name)
	}
	sort.Strings(userNames)
	onlinePairs := make([]KV, 0, len(userNames))
	for _, name := range userNames {
		onlinePairs = append(onlinePairs, KV{name, counts[name]})
	}

	usageNames := make([]string, 0, len(usage))
	for name := range usage {
		usageNames = append(usageNames, name)
	}
	sort.Strings(usageNames)
	usagePairs := make([]KV, 0, len(usageNames))
	for _, name := range usageNames {
		usagePairs = append(usagePairs, KV{name, int64(usage[name])}) // #nosec G115 -- usage is a byte counter that fits int64
	}

	nodeNames := make([]string, 0, len(online))
	for name := range online {
		nodeNames = append(nodeNames, name)
	}
	sort.Strings(nodeNames)
	nodePairs := make([]KV, 0, len(nodeNames))
	for _, name := range nodeNames {
		nodePairs = append(nodePairs, KV{name, online[name]})
	}

	Publish("users.live",
		KV{"op", "live"},
		KV{"online", onlinePairs},
		KV{"usage", usagePairs},
	)
	Publish("nodes.live", KV{"op", "live"}, KV{"online", nodePairs})
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

// RecordEvent writes one system event row (audit.record_event).
//
// The row is attributed to "system": it is a system event, not something a
// person did. An operation a person performed goes through audit.Record with
// the real username. The payload shape is identical either way, so the event
// promoter and the audit prune see the same rows.
