// Parity tests for Phase 3 telemetry: activity, notifications, metrics and the
// SSE framing the frontend EventSource consumes byte-for-byte.
package tests

import (
	"bufio"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// extraTelemetryDDL is the observability schema Phase 3 needs on top of
// testSchema (mirrors backend/db/migrations/constants.py).
const extraTelemetryDDL = `
CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT, promoted BOOLEAN NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS node_health_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  node_id INTEGER, node_name TEXT, cpu REAL, memory REAL, live_count INTEGER, latency_ms REAL,
  reachable INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS traffic_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  total_used REAL NOT NULL, active_connections INTEGER NOT NULL, online_users INTEGER NOT NULL,
  active_users INTEGER NOT NULL, total_users INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS security_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  auth_errors INTEGER NOT NULL, rejects INTEGER NOT NULL, stale_markers INTEGER NOT NULL,
  offline_nodes INTEGER NOT NULL, full_users INTEGER NOT NULL, inactive_users INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS traffic_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  user_id INTEGER NOT NULL, node_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
  delta_bytes INTEGER NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (user_id, ts, kind, node_id));
DROP TABLE IF EXISTS user_traffic_daily;
CREATE TABLE user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day));
CREATE INDEX IF NOT EXISTS idx_user_traffic_day ON user_traffic_daily(day);
`

func newTelemetryConn(t *testing.T) (*sql.DB, string) {
	t.Helper()
	conn, dir := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("telemetry schema: %v", err)
	}
	return conn, dir
}

func newTelemetryServer(t *testing.T, conn *sql.DB, dir string) (*httptest.Server, string) {
	t.Helper()
	seedOwner(t, conn, "owner", bcryptHash)
	svc := auth.NewService(conn, dir)
	inner := http.NewServeMux()
	svc.Mount(inner)
	telemetry.NewHandler(svc).Mount(inner)
	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	srv := httptest.NewServer(root)
	t.Cleanup(srv.Close)
	token, _ := login(t, srv.URL, "owner", knownPassword)["access_token"].(string)
	if token == "" {
		t.Fatal("login returned no access_token")
	}
	return srv, token
}

func TestActivityMatches(t *testing.T) {
	conn, dir := newTelemetryConn(t)
	srv, token := newTelemetryServer(t, conn, dir)

	rows := []struct {
		ts                            float64
		actor, action, target, detail any
	}{
		{100.0, "admin1", "user.create", "ann", `{"severity": "info"}`},
		{200.0, "admin2", "user.delete", "bob", nil},
		{300.0, "admin1", "user.update", "ann", nil},
	}
	for _, r := range rows {
		if _, err := conn.Exec(`INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (?,?,?,?,?)`,
			r.ts, r.actor, r.action, r.target, r.detail); err != nil {
			t.Fatalf("seed audit: %v", err)
		}
	}

	// The seeded rows are the subject of this test: the login that set the
	// session up also wrote an auth.login row, so the feed is filtered to the
	// user.* actions to keep the ordering assertion about the seeded rows.
	_, body := doJSON(t, http.MethodGet, srv.URL+"/api/activity/?action=user", token, nil)
	if body["msg"] != "Activity retrieved" || body["success"] != true {
		t.Fatalf("envelope = %v", body)
	}
	items, _ := body["data"].([]any)
	if len(items) != 3 {
		t.Fatalf("len(data) = %d, want 3", len(items))
	}
	first, _ := items[0].(map[string]any)
	if first["action"] != "user.update" || first["target"] != "ann" {
		t.Fatalf("first row = %v, want newest-by-ts (user.update)", first)
	}
	if first["detail"] != nil {
		t.Fatalf("null detail should stay null, got %v", first["detail"])
	}
	if first["actor"] != "admin1" {
		t.Fatalf("actor = %v", first["actor"])
	}

	// A sign-in is recorded with the real username, not "system".
	_, loginFeed := doJSON(t, http.MethodGet, srv.URL+"/api/activity/?action=auth.login", token, nil)
	loginRows, _ := loginFeed["data"].([]any)
	if len(loginRows) != 1 {
		t.Fatalf("auth.login rows = %d, want 1", len(loginRows))
	}
	row, _ := loginRows[0].(map[string]any)
	if row["actor"] != "owner" {
		t.Errorf("login actor = %v, want the signing-in username", row["actor"])
	}
}

func TestNotificationsShape(t *testing.T) {
	conn, dir := newTelemetryConn(t)
	srv, token := newTelemetryServer(t, conn, dir)

	if _, err := conn.Exec(`INSERT INTO nodes (id, name, address, status) VALUES (1,'offline-node','10.0.0.1',0),(2,'online-node','10.0.0.2',1)`); err != nil {
		t.Fatalf("seed nodes: %v", err)
	}
	soon := time.Now().UTC().AddDate(0, 0, 2).Format("2006-01-02")
	later := time.Now().UTC().AddDate(0, 0, 300).Format("2006-01-02")
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name, total, used, expiry_date, is_active) VALUES
		(1,'u1','ann',1000,100,?,1),
		(2,'u2','bob',1000,900,?,1)`, soon, later); err != nil {
		t.Fatalf("seed users: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO node_health_snapshots (ts, node_id, node_name, cpu, reachable) VALUES (?,2,'online-node',90,1)`, time.Now().Unix()); err != nil {
		t.Fatalf("seed cpu: %v", err)
	}

	_, body := doJSON(t, http.MethodGet, srv.URL+"/api/notifications/", token, nil)
	items, _ := body["data"].([]any)
	if len(items) != 3 {
		t.Fatalf("len(data) = %d, want 3 (%v)", len(items), items)
	}
	got := map[string]string{}
	for _, it := range items {
		m, _ := it.(map[string]any)
		typ, _ := m["type"].(string)
		target, _ := m["target"].(string)
		got[typ+":"+target] = m["title"].(string)
	}
	if _, ok := got["node_offline:offline-node"]; !ok {
		t.Fatalf("missing node_offline: %v", got)
	}
	if _, ok := got["threshold_usage:bob"]; ok {
		t.Fatalf("usage rows must stay out of the inbox: %v", got)
	}
	if title := got["threshold_expiry:ann"]; title != "ann expires in 2 day(s)" {
		t.Fatalf("expiry title = %q", title)
	}
	if title := got["threshold_cpu:online-node"]; title != "Node online-node CPU at 90% (warn limit 85%)" {
		t.Fatalf("cpu title = %q", title)
	}
}

func TestSSEFramingMatches(t *testing.T) {
	conn, dir := newTelemetryConn(t)
	srv, token := newTelemetryServer(t, conn, dir)

	req, _ := http.NewRequest(http.MethodGet, srv.URL+"/api/live/stream", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("stream: %v", err)
	}
	defer resp.Body.Close()
	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("content-type = %q", ct)
	}
	if resp.Header.Get("X-Accel-Buffering") != "no" || resp.Header.Get("Cache-Control") != "no-cache" {
		t.Fatalf("SSE headers = %v", resp.Header)
	}

	rd := bufio.NewReader(resp.Body)
	ready := readFrame(t, rd)
	if !strings.HasPrefix(ready, "event: ready\ndata: {\"ts\": ") || !strings.HasSuffix(ready, ", \"cap\": 50}") {
		t.Fatalf("ready frame = %q", ready)
	}
	if strings.Contains(ready, "retry:") {
		t.Fatalf("retry field must not be added: %q", ready)
	}

	telemetry.DefaultBus.Publish("users", telemetry.KV{Key: "op", Val: "sync"})
	evt := readFrame(t, rd)
	if !strings.HasPrefix(evt, "event: users\ndata: {\"op\": \"sync\", \"ts\": ") || !strings.HasSuffix(evt, "}") {
		t.Fatalf("event frame = %q", evt)
	}
	// The ts value must be a plain float, not Go's %v int form.
	payload := strings.SplitN(evt, "data: ", 2)[1]
	var decoded map[string]any
	if err := json.Unmarshal([]byte(payload), &decoded); err != nil {
		t.Fatalf("event data not JSON: %q (%v)", payload, err)
	}
	if _, ok := decoded["ts"].(float64); !ok {
		t.Fatalf("ts not a float: %v", decoded["ts"])
	}
}

// readFrame reads one `...\n\n` SSE frame, terminator stripped.
func readFrame(t *testing.T, rd *bufio.Reader) string {
	t.Helper()
	var sb strings.Builder
	for {
		line, err := rd.ReadString('\n')
		if err != nil {
			t.Fatalf("read frame: %v (have %q)", err, sb.String())
		}
		if line == "\n" {
			return strings.TrimSuffix(sb.String(), "\n")
		}
		sb.WriteString(line)
	}
}

// TestPromoteEventsDeliversOnce seeds delivered rows and asserts each system
// event is promoted at most once.
func TestPromoteEventsDeliversOnce(t *testing.T) {
	conn, _ := newTelemetryConn(t)
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`); err != nil {
		t.Fatal(err)
	}

	for i := 0; i < 2; i++ {
		key := "key" + string(rune('a'+i))
		detail := `{"severity":"info","message":"msg ` + key + `","meta":{"event_key":"` + key + `"}}`
		if _, err := conn.Exec(`INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (?,?,?,?,?)`,
			float64(100+i), "system", "threshold.test", "t", detail); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := conn.Exec(`INSERT INTO delivered (subscription, event_key, ts) VALUES (?,?,?)`, "threshold.test", "keya", 1.0); err != nil {
		t.Fatal(err)
	}

	calls := 0
	sent := telemetry.PromoteEvents(conn, func(msg string) bool { calls++; return true })
	if sent != 1 {
		t.Fatalf("sent = %d, want 1", sent)
	}
	if calls != 1 {
		t.Fatalf("send calls = %d, want 1", calls)
	}

	sent2 := telemetry.PromoteEvents(conn, func(msg string) bool { calls++; return true })
	if sent2 != 0 {
		t.Fatalf("second pass sent = %d, want 0", sent2)
	}
}

// TestPruneAuditLogsKeepsRecentAndUndelivered checks date and delivered gating.
func TestPruneAuditLogsKeepsRecentAndUndelivered(t *testing.T) {
	conn, _ := newTelemetryConn(t)
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`); err != nil {
		t.Fatal(err)
	}

	old := float64(1000)
	recent := float64(time.Now().Unix())
	detail := `{"severity":"info","message":"old","meta":{"event_key":"k1"}}`
	if _, err := conn.Exec(`INSERT INTO audit_logs (ts, actor, action, detail) VALUES (?,?,?,?)`, old, "system", "a", detail); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO delivered (subscription, event_key, ts) VALUES (?,?,?)`, "a", "k1", old); err != nil {
		t.Fatal(err)
	}
	detail2 := `{"severity":"info","message":"old2","meta":{"event_key":"k2"}}`
	if _, err := conn.Exec(`INSERT INTO audit_logs (ts, actor, action, detail) VALUES (?,?,?,?)`, old, "system", "b", detail2); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO audit_logs (ts, actor, action, detail) VALUES (?,?,?,?)`, recent, "system", "c", detail2); err != nil {
		t.Fatal(err)
	}

	removed := telemetry.PruneAuditLogs(conn, 1)
	if removed != 1 {
		t.Fatalf("removed = %d, want 1", removed)
	}
	var n int
	_ = conn.QueryRow(`SELECT COUNT(*) FROM audit_logs`).Scan(&n)
	if n != 2 {
		t.Fatalf("remaining = %d, want 2", n)
	}
}
