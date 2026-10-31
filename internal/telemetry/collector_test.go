package telemetry

import (
	"database/sql"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
)

// collectorSchema is the slice of the panel schema the collector reads.
const collectorSchema = `
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  tunnel_address VARCHAR, protocol VARCHAR DEFAULT 'tcp', ovpn_port INTEGER DEFAULT 1194,
  port INTEGER DEFAULT 2083, key VARCHAR, status BOOLEAN DEFAULT 1, server_ca VARCHAR,
  country_code VARCHAR, latitude REAL, longitude REAL, extra_ports VARCHAR DEFAULT '');
CREATE TABLE settings (id INTEGER PRIMARY KEY, panel_id VARCHAR, panel_domain VARCHAR);
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, expiry_date DATE, is_active BOOLEAN DEFAULT 1, tag VARCHAR,
  last_online VARCHAR);
CREATE TABLE settings_kv (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at FLOAT);
`

func newCollectorDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "collector.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(collectorSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn
}

// resetLiveState clears the process-wide node registry and snapshot so a test
// starts from a known-empty collector.
func resetLiveState() {
	snap.mu.Lock()
	snap.connections = map[string]int{}
	snap.nodes = map[string]bool{}
	snap.lastPoll = 0
	snap.mu.Unlock()
	nodeAlerts.mu.Lock()
	nodeAlerts.graceUntil = map[string]float64{}
	nodeAlerts.mu.Unlock()
}

// fakeNode starts a TLS node answering /sync/sessions with the given data
// object. When block is non-nil the handler waits on it before answering, so a
// test can drive a node past the fan-out deadline without ever sleeping.
func fakeNode(t *testing.T, sessions string, block <-chan struct{}) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/sessions", func(w http.ResponseWriter, r *http.Request) {
		if block != nil {
			<-block
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":` + sessions + `}`))
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

// addNode inserts an active node pinned to srv's certificate.
func addNode(t *testing.T, conn *sql.DB, id int64, name string, srv *httptest.Server) {
	t.Helper()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	port, _ := strconv.Atoi(u.Port())
	pin := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, port, status, server_ca) VALUES (?, ?, ?, ?, 1, ?)`,
		id, name, u.Hostname(), port, pin,
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}
}

// TestCollectLiveSnapshotFanout: one node answers, one hangs past the deadline;
// the tick still completes, marks the slow node offline, the fast one online.
func TestCollectLiveSnapshotFanout(t *testing.T) {
	old := liveFanoutDeadline
	liveFanoutDeadline = 300 * time.Millisecond
	t.Cleanup(func() { liveFanoutDeadline = old })
	resetLiveState()
	conn := newCollectorDB(t)

	release := make(chan struct{})
	slow := fakeNode(t, `{"live_sessions":[]}`, release)
	t.Cleanup(func() { close(release) }) // LIFO: runs before slow.Close
	fast := fakeNode(t, `{"live_sessions":[]}`, nil)
	addNode(t, conn, 1, "fast", fast)
	addNode(t, conn, 2, "slow", slow)

	start := time.Now()
	CollectLiveSnapshot(conn)
	if elapsed := time.Since(start); elapsed > node.RequestFanoutDeadline {
		t.Fatalf("tick took %v, want within %v", elapsed, node.RequestFanoutDeadline)
	}
	online := NodeOnline()
	if !online["fast"] {
		t.Errorf("fast node = %v, want online", online["fast"])
	}
	if online["slow"] {
		t.Errorf("slow node = %v, want offline", online["slow"])
	}
	if !SnapshotFresh() {
		t.Errorf("snapshot should be fresh after a tick")
	}
}

// TestCollectMetricsFanout: one node answers, one hangs past the deadline; the
// pass still completes within the deadline instead of waiting out the hung
// node's own 10 s + 30 s timeouts one after another.
func TestCollectMetricsFanout(t *testing.T) {
	old := metricsFanoutDeadline
	metricsFanoutDeadline = 1 * time.Second
	t.Cleanup(func() { metricsFanoutDeadline = old })
	resetLiveState()
	conn := newCollectorDB(t)

	release := make(chan struct{})
	slow := fakeNode(t, `{"live_sessions":[]}`, release)
	t.Cleanup(func() { close(release) }) // LIFO: runs before slow.Close
	fast := fakeNode(t, `{"live_sessions":[]}`, nil)
	addNode(t, conn, 1, "fast", fast)
	addNode(t, conn, 2, "slow", slow)

	start := time.Now()
	CollectMetrics(conn)
	if elapsed := time.Since(start); elapsed > metricsFanoutDeadline+500*time.Millisecond {
		t.Fatalf("collect took %v, want within %v", elapsed, metricsFanoutDeadline)
	}
}

// TestCollectLiveSnapshotIdleNodeOnline guards review-focus #1: a node that
// answers with zero live sessions is online with zero connections.
func TestCollectLiveSnapshotIdleNodeOnline(t *testing.T) {
	resetLiveState()
	conn := newCollectorDB(t)
	addNode(t, conn, 1, "idle", fakeNode(t, `{"live_sessions":[]}`, nil))

	CollectLiveSnapshot(conn)

	if !NodeOnline()["idle"] {
		t.Errorf("idle node = offline, want online")
	}
	if c := Connections(); len(c) != 0 {
		t.Errorf("connections = %v, want empty", c)
	}
}

// TestCollectLiveSnapshotCNMapping: a numeric CN resolves through id -> name.
func TestCollectLiveSnapshotCNMapping(t *testing.T) {
	resetLiveState()
	conn := newCollectorDB(t)
	if _, err := conn.Exec(`INSERT INTO users (id, name) VALUES (42, 'alice')`); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	addNode(t, conn, 1, "n1", fakeNode(t, `{"live_sessions":[{"common_name":"42"}]}`, nil))

	CollectLiveSnapshot(conn)

	if got := Connections()["alice"]; got != 1 {
		t.Errorf("alice connections = %d, want 1", got)
	}
}

// TestCollectLiveSnapshotNameFallback: an unmapped name-shaped CN resolves via
// ExtractUsername stripping the node-name suffix.
func TestCollectLiveSnapshotNameFallback(t *testing.T) {
	resetLiveState()
	conn := newCollectorDB(t)
	if _, err := conn.Exec(`INSERT INTO users (id, name) VALUES (7, 'bob')`); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	addNode(t, conn, 1, "nodeA", fakeNode(t, `{"live_sessions":[{"common_name":"bob-nodeA"}]}`, nil))

	CollectLiveSnapshot(conn)

	if got := Connections()["bob"]; got != 1 {
		t.Errorf("bob connections = %d, want 1", got)
	}
}

// TestApplyGrace walks the up->down grace transitions.
func TestApplyGrace(t *testing.T) {
	resetLiveState()

	// A node never seen up does not get grace.
	if got := applyGrace(map[string]bool{"x": false}, map[string]bool{}, 100); got["x"] {
		t.Errorf("never-seen node = online, want down")
	}

	now := 1000.0
	// First down tick for a previously-up node arms grace and holds it up.
	if got := applyGrace(map[string]bool{"a": false}, map[string]bool{"a": true}, now); !got["a"] {
		t.Errorf("first down tick = offline, want held up by grace")
	}
	// Within the grace window it still holds up.
	if got := applyGrace(map[string]bool{"a": false}, map[string]bool{"a": true}, now+graceSeconds-1); !got["a"] {
		t.Errorf("within grace = offline, want up")
	}
	// Past the window it goes down.
	if got := applyGrace(map[string]bool{"a": false}, map[string]bool{"a": true}, now+graceSeconds+1); got["a"] {
		t.Errorf("past grace = online, want down")
	}
}

// TestTouchLastOnline stamps every name in one statement and leaves the rest.
func TestTouchLastOnline(t *testing.T) {
	conn := newCollectorDB(t)
	stamp := "2026-10-26 12:00:00.000000"
	if _, err := conn.Exec(`INSERT INTO users (id, name) VALUES (1, 'alice'), (2, 'bob'), (3, 'carol')`); err != nil {
		t.Fatalf("seed: %v", err)
	}

	touchLastOnline(conn, []string{"alice", "carol"}, stamp)

	var alice, bob string
	_ = conn.QueryRow(`SELECT COALESCE(last_online, '') FROM users WHERE name = 'alice'`).Scan(&alice)
	_ = conn.QueryRow(`SELECT COALESCE(last_online, '') FROM users WHERE name = 'bob'`).Scan(&bob)
	if alice != stamp {
		t.Errorf("alice last_online = %q, want %q", alice, stamp)
	}
	if bob != "" {
		t.Errorf("bob last_online = %q, want untouched", bob)
	}
}

func TestResolveSessionUsernameForms(t *testing.T) {
	idToName := map[string]string{"42": "alice"}
	known := map[string]bool{"alice": true, "bob": true}
	for _, tc := range []struct {
		commonName string
		want       string
	}{
		{commonName: "42", want: "alice"},
		{commonName: "42-nodeA", want: "alice"},
		{commonName: "alice-nodeA", want: "alice"},
		{commonName: "bob", want: "bob"},
	} {
		if got := resolveSessionUsername(tc.commonName, "nodeA", idToName, known); got != tc.want {
			t.Errorf("resolveSessionUsername(%q) = %q, want %q", tc.commonName, got, tc.want)
		}
	}
}

func TestResolveSessionUsernamePrefersNumericUsernameOverCollidingID(t *testing.T) {
	idToName := map[string]string{"42": "alice", "99": "42"}
	known := map[string]bool{"alice": true, "42": true}
	for _, commonName := range []string{"42", "42-nodeA"} {
		if got := resolveSessionUsername(commonName, "nodeA", idToName, known); got != "42" {
			t.Errorf("resolveSessionUsername(%q) = %q, want the known numeric username", commonName, got)
		}
	}
}

// TestCollectMetricsResolvesNodeSuffixedCommonNames verifies that the metrics
// collector applies the same node-name suffix mapping as the live snapshot.
func TestCollectMetricsResolvesNodeSuffixedCommonNames(t *testing.T) {
	resetLiveState()
	conn := newCollectorDB(t)
	if _, err := conn.Exec(`CREATE TABLE security_snapshots (
		id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, auth_errors INTEGER NOT NULL,
		rejects INTEGER NOT NULL, stale_markers INTEGER NOT NULL, offline_nodes INTEGER NOT NULL,
		full_users INTEGER NOT NULL, inactive_users INTEGER NOT NULL)`); err != nil {
		t.Fatalf("create security snapshots: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO users (id, name, max_logins) VALUES (42, 'alice', 1)`); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	addNode(t, conn, 1, "nodeA", fakeNode(t,
		`{"live_count":1,"live_sessions":[{"common_name":"alice-nodeA"}]}`, nil))

	CollectMetrics(conn)

	var fullUsers int64
	if err := conn.QueryRow(`SELECT full_users FROM security_snapshots ORDER BY id DESC LIMIT 1`).Scan(&fullUsers); err != nil {
		t.Fatalf("read security snapshot: %v", err)
	}
	if fullUsers != 1 {
		t.Errorf("full_users = %d, want 1 for alice's active device", fullUsers)
	}
}
