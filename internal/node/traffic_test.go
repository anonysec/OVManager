package node

import (
	"database/sql"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/db"
)

// trafficSchema mirrors the columns SyncTraffic touches.
const trafficSchema = `
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  tunnel_address VARCHAR, protocol VARCHAR DEFAULT 'tcp', ovpn_port INTEGER DEFAULT 1194,
  port INTEGER DEFAULT 2083, key VARCHAR, status BOOLEAN DEFAULT 1, server_ca VARCHAR,
  country_code VARCHAR, latitude REAL, longitude REAL, extra_ports VARCHAR DEFAULT '');
CREATE TABLE settings (id INTEGER PRIMARY KEY, panel_id VARCHAR, panel_domain VARCHAR);
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, expiry_date DATE, is_active BOOLEAN DEFAULT 1, tag VARCHAR);
CREATE TABLE settings_kv (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at FLOAT);
CREATE TABLE user_traffic_daily (id INTEGER PRIMARY KEY, user_id INTEGER, day DATE, bytes BIGINT,
  UNIQUE(user_id, day));
`

func newTrafficDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "traffic.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(trafficSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn
}

// usageServer is a pinned fake node answering GET /sync/usage.
func usageServer(t *testing.T, totals map[string]any, delay time.Duration) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/usage", func(w http.ResponseWriter, r *http.Request) {
		if delay > 0 {
			time.Sleep(delay)
		}
		w.Header().Set("Content-Type", "application/json")
		body, _ := json.Marshal(map[string]any{
			"success": true,
			"data":    map[string]any{"totals": totals},
		})
		_, _ = w.Write(body)
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func seedTrafficNode(t *testing.T, conn *sql.DB, id int64, name string, srv *httptest.Server) {
	t.Helper()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatalf("parse port: %v", err)
	}
	pin := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, port, key, status, server_ca) VALUES (?, ?, ?, ?, 'k', 1, ?)`,
		id, name, u.Hostname(), port, pin,
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}
}

func seedTrafficUser(t *testing.T, conn *sql.DB, id int64, name, used, nodeUsage string) {
	t.Helper()
	if _, err := conn.Exec(
		`INSERT INTO users (id, uuid, name, used, node_usage) VALUES (?, ?, ?, `+used+`, ?)`,
		id, name, name, nodeUsage,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}
}

func userUsed(t *testing.T, conn *sql.DB, id int64) int64 {
	t.Helper()
	var used sql.NullInt64
	if err := conn.QueryRow(`SELECT used FROM users WHERE id = ?`, id).Scan(&used); err != nil {
		t.Fatalf("read used: %v", err)
	}
	return used.Int64
}

func userState(t *testing.T, conn *sql.DB, id int64) map[string]any {
	t.Helper()
	var raw string
	if err := conn.QueryRow(`SELECT COALESCE(node_usage,'{}') FROM users WHERE id = ?`, id).Scan(&raw); err != nil {
		t.Fatalf("read node_usage: %v", err)
	}
	out := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		t.Fatalf("node_usage %q: %v", raw, err)
	}
	return out
}

func TestSyncTrafficBillsTwoNodes(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficNode(t, conn, 2, "n2", usageServer(t, map[string]any{"alice": int64(2000)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":0,"2":0}`)

	res := SyncTraffic(conn)
	if res.NodesPolled != 2 {
		t.Errorf("NodesPolled = %d, want 2", res.NodesPolled)
	}
	if res.BytesBilled != 3000 {
		t.Errorf("BytesBilled = %d, want 3000", res.BytesBilled)
	}
	if res.UsersUpdated != 1 {
		t.Errorf("UsersUpdated = %d, want 1", res.UsersUpdated)
	}
	if got := userUsed(t, conn, 1); got != 3000 {
		t.Errorf("used = %d, want 3000", got)
	}
}

func TestSyncTrafficSkipsDeletedUser(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"ghost": int64(500)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", "{}")

	res := SyncTraffic(conn)
	if res.NodesPolled != 1 {
		t.Errorf("NodesPolled = %d, want 1", res.NodesPolled)
	}
	if res.UsersUpdated != 0 || res.UsersSeeded != 0 || res.BytesBilled != 0 {
		t.Errorf("result = %+v, want no updates", res)
	}
}

func TestSyncTrafficOCCRetry(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":0}`)

	hookCalls := 0
	trafficTestHook = func() {
		hookCalls++
		// A concurrent SyncAllUserLimits merges push_hash into the same JSON.
		if _, err := conn.Exec(`UPDATE users SET node_usage='{"1":0,"push_hash":{"1":"x"}}' WHERE id=1`); err != nil {
			t.Fatalf("hook update: %v", err)
		}
		trafficTestHook = nil
	}
	defer func() { trafficTestHook = nil }()

	res := SyncTraffic(conn)
	if hookCalls != 1 {
		t.Errorf("hook calls = %d, want 1", hookCalls)
	}
	if res.BytesBilled != 1000 {
		t.Errorf("BytesBilled = %d, want 1000 (billed once)", res.BytesBilled)
	}
	if got := userUsed(t, conn, 1); got != 1000 {
		t.Errorf("used = %d, want 1000 (billed once)", got)
	}
	if state := userState(t, conn, 1); state["push_hash"] == nil {
		t.Errorf("push_hash lost: %v", state)
	}
}

func TestSyncTrafficFirstPollSeeds(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", "{}")

	res := SyncTraffic(conn)
	if res.BytesBilled != 0 {
		t.Errorf("BytesBilled = %d, want 0 on first poll", res.BytesBilled)
	}
	if res.UsersSeeded != 1 || res.UsersUpdated != 0 {
		t.Errorf("seeded/updated = %d/%d, want 1/0", res.UsersSeeded, res.UsersUpdated)
	}
	if state := userState(t, conn, 1); state["1"] != float64(1000) {
		t.Errorf(`node_usage["1"] = %v, want 1000`, state["1"])
	}
}

func TestSyncTrafficNullUsed(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "NULL", `{"1":0}`)

	res := SyncTraffic(conn)
	if res.BytesBilled != 1000 {
		t.Errorf("BytesBilled = %d, want 1000", res.BytesBilled)
	}
	if got := userUsed(t, conn, 1); got != 1000 {
		t.Errorf("used = %d, want 1000 (NULL must still bill)", got)
	}
}

func TestSyncTrafficNodeTimeout(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficNode(t, conn, 2, "n2", usageServer(t, map[string]any{"alice": int64(5000)}, 2*time.Second))
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":0,"2":0}`)

	old := trafficFanoutDeadline
	trafficFanoutDeadline = 300 * time.Millisecond
	defer func() { trafficFanoutDeadline = old }()

	res := SyncTraffic(conn)
	if res.NodesFailed != 1 {
		t.Errorf("NodesFailed = %d, want 1", res.NodesFailed)
	}
	if res.NodesPolled != 1 {
		t.Errorf("NodesPolled = %d, want 1", res.NodesPolled)
	}
	if res.BytesBilled != 1000 {
		t.Errorf("BytesBilled = %d, want 1000 (fast node still applied)", res.BytesBilled)
	}
	if got := userUsed(t, conn, 1); got != 1000 {
		t.Errorf("used = %d, want 1000", got)
	}
}

func TestSyncTrafficReseedMarker(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(600)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":500,"__reseed":true}`)

	res := SyncTraffic(conn)
	if res.BytesBilled != 0 {
		t.Errorf("BytesBilled = %d, want 0 after reseed", res.BytesBilled)
	}
	state := userState(t, conn, 1)
	if state["1"] != float64(600) {
		t.Errorf(`node_usage["1"] = %v, want 600`, state["1"])
	}
	if _, ok := state[ReseedMarkerKey]; ok {
		t.Errorf("marker not cleared: %v", state)
	}
}

func TestSyncTrafficNullTotalsCountsPolled(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, nil, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", "{}")

	res := SyncTraffic(conn)
	if res.NodesPolled != 1 {
		t.Errorf("NodesPolled = %d, want 1", res.NodesPolled)
	}
	if res.NodesFailed != 0 {
		t.Errorf("NodesFailed = %d, want 0", res.NodesFailed)
	}
}

// A node may report more than one key for the same user: the node's
// /sync/usage merges alias CNs additively (OVNode get_users_usage), so each
// key is a DIFFERENT byte pool. The panel must sum them — keeping only the
// larger one drops the other's bytes from users.used, from
// user_traffic_daily and from the baseline, permanently.
func TestSyncTrafficSumsAliasKeys(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	// The node reports the same user under its name and under its numeric id.
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{
		"alice": int64(700),
		"12":    int64(300),
	}, 0))
	seedTrafficUser(t, conn, 12, "alice", "0", `{"1":0}`)

	res := SyncTraffic(conn)
	if res.BytesBilled != 1000 {
		t.Errorf("BytesBilled = %d, want 1000 (700 + 300)", res.BytesBilled)
	}
	if got := userUsed(t, conn, 12); got != 1000 {
		t.Errorf("used = %d, want 1000", got)
	}
	if got := userState(t, conn, 12)["1"]; got != float64(1000) {
		t.Errorf(`node_usage["1"] = %v, want 1000`, got)
	}
}

// The first poll must still SEED the baseline (delta 0), never bill a node's
// lifetime total — including when the total is a sum of alias pools.
func TestSyncTrafficAliasSumSeedsOnFirstPoll(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{
		"alice": int64(700),
		"12":    int64(300),
	}, 0))
	seedTrafficUser(t, conn, 12, "alice", "0", "{}")

	res := SyncTraffic(conn)
	if res.BytesBilled != 0 {
		t.Errorf("BytesBilled = %d, want 0 on the first poll", res.BytesBilled)
	}
	if res.UsersSeeded != 1 {
		t.Errorf("UsersSeeded = %d, want 1", res.UsersSeeded)
	}
	if got := userState(t, conn, 12)["1"]; got != float64(1000) {
		t.Errorf(`node_usage["1"] = %v, want 1000 (the seeded sum)`, got)
	}
}

// A collision is reported so a node whose keying has drifted is visible
// instead of silent.
func TestSyncTrafficAliasCollisionVisible(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{
		"alice": int64(700),
		"12":    int64(300),
	}, 0))
	seedTrafficUser(t, conn, 12, "alice", "0", `{"1":0}`)

	res := SyncTraffic(conn)
	if len(res.AliasCollisions) != 1 {
		t.Fatalf("AliasCollisions = %v, want exactly 1", res.AliasCollisions)
	}
	msg := res.AliasCollisions[0]
	for _, want := range []string{"alice", "node=1", "12"} {
		if !strings.Contains(msg, want) {
			t.Errorf("collision %q does not name %q", msg, want)
		}
	}
}

// A node that reports one key per user (the documented contract) must not
// report a collision.
func TestSyncTrafficNoCollisionForOneKey(t *testing.T) {
	resetForTests()
	defer resetForTests()
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "n1", usageServer(t, map[string]any{"alice": int64(1000)}, 0))
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":0}`)

	res := SyncTraffic(conn)
	if len(res.AliasCollisions) != 0 {
		t.Errorf("AliasCollisions = %v, want none", res.AliasCollisions)
	}
	if res.BytesBilled != 1000 {
		t.Errorf("BytesBilled = %d, want 1000", res.BytesBilled)
	}
}

// A node that hangs must not hold a concurrency slot for its whole timeout:
// with more nodes than slots, the dead ones would starve the healthy ones
// queued behind them, and the panel would report EVERY node as dead and bill
// nothing.
//
// Whether the healthy call wins the slot or queues behind the hanging one is
// a scheduling race, so the scenario runs several times: without the fix the
// healthy node is only billed when it happens to win the slot, and with the
// fix it is billed either way.
func TestSyncTrafficBillsHealthyNodesBehindHangingOnes(t *testing.T) {
	resetForTests()
	defer resetForTests()
	restore := setFanoutLimit(1)
	defer restore()
	oldDeadline := trafficFanoutDeadline
	trafficFanoutDeadline = 600 * time.Millisecond
	defer func() { trafficFanoutDeadline = oldDeadline }()

	for attempt := 0; attempt < 6; attempt++ {
		conn := newTrafficDB(t)
		// The dead node answers late; the live node answers at once.
		seedTrafficNode(t, conn, 1, "dead", usageServer(t, map[string]any{"alice": int64(500)}, 1500*time.Millisecond))
		seedTrafficNode(t, conn, 2, "live", usageServer(t, map[string]any{"alice": int64(700)}, 0))
		seedTrafficUser(t, conn, 1, "alice", "0", `{"1":0,"2":0}`)

		res := SyncTraffic(conn)

		// The healthy node must be billed: its 700 bytes, not the dead
		// node's 500.
		if res.BytesBilled != 700 {
			t.Errorf("attempt %d: BytesBilled = %d, want 700 (the healthy node only)", attempt+1, res.BytesBilled)
			continue
		}
		if got := userUsed(t, conn, 1); got != 700 {
			t.Errorf("attempt %d: used = %d, want 700", attempt+1, got)
		}
	}
}
