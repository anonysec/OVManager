package panel

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync/atomic"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
)

// trafficSchema covers the columns SyncTraffic and the owner gate touch.
const trafficSchema = `
CREATE TABLE admins (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
  is_owner BOOLEAN DEFAULT 0, telegram_id INTEGER);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, token_hash VARCHAR UNIQUE, username VARCHAR,
  role VARCHAR, created_at FLOAT, expires_at FLOAT, last_seen_at FLOAT,
  user_agent VARCHAR, ip VARCHAR);
CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR UNIQUE, used BIGINT,
  node_usage VARCHAR DEFAULT '{}');
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  status BOOLEAN DEFAULT 1, key VARCHAR);
CREATE TABLE settings (id INTEGER PRIMARY KEY, panel_id VARCHAR, bot_enabled BOOLEAN DEFAULT 0);
`

func newTrafficDB(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "traffic.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(trafficSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn, dir
}

// TestSyncTrafficRouteZeroCounts mounts the panel (starting the traffic worker
// against a node-less DB) and drives POST /maintenance/sync-traffic as the
// owner. Empty DB => success with a zero TrafficResult, and Mount must not
// panic while launching the worker.
func TestSyncTrafficRouteZeroCounts(t *testing.T) {
	conn, dir := newTrafficDB(t)
	if _, err := conn.Exec(
		`INSERT INTO admins (id, username, password, is_owner) VALUES (1, 'owner', 'x', 1)`,
	); err != nil {
		t.Fatalf("seed owner: %v", err)
	}
	svc := auth.NewService(conn, dir)
	h := NewHandler(svc)

	mux := http.NewServeMux()
	h.Mount(mux) // starts startTrafficWorker; must not panic

	token, err := svc.CreateSession("owner", "owner", "", "", 0)
	if err != nil {
		t.Fatalf("create session: %v", err)
	}
	srv := httptest.NewServer(mux)
	defer srv.Close()

	req, err := http.NewRequest(http.MethodPost, srv.URL+"/maintenance/sync-traffic", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer "+token)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST sync-traffic: %v", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}

	var body struct {
		Success bool               `json:"success"`
		Data    node.TrafficResult `json:"data"`
	}
	if err := json.NewDecoder(res.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !body.Success {
		t.Fatalf("success = false, want true")
	}
	if body.Data != (node.TrafficResult{}) {
		t.Fatalf("result = %+v, want zero TrafficResult", body.Data)
	}
}

// TestTrafficWorkerIgnoresTelegram pins that the poll runs with the bot
// disabled: the worker's tick must still call SyncTraffic. It must not ride
// the Telegram ready() gate.
func TestTrafficWorkerIgnoresTelegram(t *testing.T) {
	conn, dir := newTrafficDB(t)
	if _, err := conn.Exec(`INSERT INTO settings (id, bot_enabled) VALUES (1, 0)`); err != nil {
		t.Fatalf("seed settings: %v", err)
	}
	h := NewHandler(auth.NewService(conn, dir))

	var calls atomic.Int32
	restore := setTrafficSync(func(*sql.DB) node.TrafficResult {
		calls.Add(1)
		return node.TrafficResult{}
	})
	t.Cleanup(restore)

	h.startTrafficWorker() // idempotent; must not panic
	h.trafficTick()

	if got := calls.Load(); got != 1 {
		t.Fatalf("SyncTraffic calls after one tick = %d, want 1", got)
	}
}

// TestTrafficPollSeconds pins the OVM_TRAFFIC_POLL_SECONDS default and override.
func TestTrafficPollSeconds(t *testing.T) {
	t.Setenv("OVM_TRAFFIC_POLL_SECONDS", "")
	if got := trafficPollSeconds(); got != 60 {
		t.Fatalf("default = %d, want 60", got)
	}
	t.Setenv("OVM_TRAFFIC_POLL_SECONDS", "15")
	if got := trafficPollSeconds(); got != 15 {
		t.Fatalf("override = %d, want 15", got)
	}
}
