// Node parity tests: TLS pin accept/reject, fail-closed fallback, status
// shapes, unreachable semantics, fanout chunking and sync result shape.
package goparity

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"database/sql"
	"encoding/pem"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"ovmanager-go/internal/db"
	"ovmanager-go/internal/node"
)

// nodeSchema mirrors the columns backend/node/*.py touches.
const nodeSchema = `
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  tunnel_address VARCHAR, protocol VARCHAR DEFAULT 'tcp', ovpn_port INTEGER DEFAULT 1194,
  port INTEGER DEFAULT 2083, key VARCHAR, status BOOLEAN DEFAULT 1, server_ca VARCHAR,
  country_code VARCHAR, latitude REAL, longitude REAL);
CREATE TABLE settings (id INTEGER PRIMARY KEY, panel_id VARCHAR, panel_domain VARCHAR);
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, expiry_date DATE, is_active BOOLEAN DEFAULT 1, tag VARCHAR);
CREATE TABLE settings_kv (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at FLOAT);
`

// newNodeDB opens a throwaway SQLite with the node schema.
func newNodeDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "node.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(nodeSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn
}

// hostPort splits an httptest URL into host and port.
func hostPort(t *testing.T, raw string) (string, int) {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatalf("parse %s: %v", raw, err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatalf("port %s: %v", u.Port(), err)
	}
	return u.Hostname(), port
}

// certPEM renders a server's certificate as PEM, like the panel's stored pin.
func certPEM(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
}

// selfSignedPEM mints a fresh self-signed certificate PEM that cannot match any
// httptest server's shared certificate.
func selfSignedPEM(t *testing.T) string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "not-the-node"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}))
}

// syncHandler answers the two routes get_node_status fans out to.
func syncHandler(version string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"msg":"ok","data":{"version":"` + version + `"}}`))
	})
	mux.HandleFunc("/sync/sessions", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":{"live_sessions":[],"stale_markers":[],"auth_errors":0}}`))
	})
	return mux
}

// TestNodePinAcceptsMatchingCert: a pin equal to the served cert is trusted.
func TestNodePinAcceptsMatchingCert(t *testing.T) {
	srv := httptest.NewTLSServer(syncHandler("1.6.0"))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	c, err := node.NewClient(host, port, "api-key", certPEM(t, srv), "", 1)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	if !c.CheckNode() {
		t.Fatalf("pinned client should reach the node")
	}
	if c.TLSMode() != "verified" {
		t.Errorf("tls_mode = %q, want verified", c.TLSMode())
	}
}

// TestNodePinRejectsMismatchedCert: a pin for a different cert fails closed,
// even with NODE_TLS_INSECURE_FALLBACK opted in (a pin never falls back).
func TestNodePinRejectsMismatchedCert(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "true")
	srv := httptest.NewTLSServer(syncHandler("1.6.0"))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	// httptest reuses one process-wide cert, so mint a genuinely different one.
	c, err := node.NewClient(host, port, "api-key", selfSignedPEM(t), "", 1)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	if c.CheckNode() {
		t.Fatalf("mismatched pin must be rejected")
	}
	if c.ConflictMsg() != "" {
		t.Errorf("conflict_msg = %q, want empty", c.ConflictMsg())
	}
}

// TestNodeFallbackFailClosed: no pin + self-signed node + fallback off → fail.
func TestNodeFallbackFailClosed(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "")
	srv := httptest.NewTLSServer(syncHandler("1.6.0"))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	c, err := node.NewClient(host, port, "api-key", "", "", 1)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	if c.CheckNode() {
		t.Fatalf("unverified TLS must fail closed while fallback is off")
	}
}

// TestNodeFallbackOptIn: the same node is reachable once the flag is set.
func TestNodeFallbackOptIn(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "true")
	srv := httptest.NewTLSServer(syncHandler("1.6.0"))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	c, err := node.NewClient(host, port, "api-key", "", "", 1)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	if !c.CheckNode() {
		t.Fatalf("fallback opt-in should connect to a self-signed node")
	}
	if c.TLSMode() != "unverified-self-signed" {
		t.Errorf("tls_mode = %q, want unverified-self-signed", c.TLSMode())
	}
}

// TestNodeConflictEnvelope: a 409 records the node's own message and returns a
// conflict envelope when the caller opted in.
func TestNodeConflictEnvelope(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"detail":"Node is paired with another panel."}`))
	}))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	c, err := node.NewClient(host, port, "api-key", certPEM(t, srv), "", 1)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	got := c.UpdateConfig(node.UpdateConfigParams{TunnelAddress: "", Protocol: "tcp", OVPNPort: 1194, ReturnEnvelope: true})
	env, ok := got.(map[string]any)
	if !ok {
		t.Fatalf("update_config = %#v, want conflict envelope", got)
	}
	if env["conflict"] != true || env["success"] != false {
		t.Errorf("envelope = %#v, want success=false conflict=true", env)
	}
	if env["msg"] != "Node is paired with another panel." {
		t.Errorf("msg = %v", env["msg"])
	}
	if c.ConflictMsg() != "Node is paired with another panel." {
		t.Errorf("conflict_msg = %q", c.ConflictMsg())
	}
}

// TestNodeStatusShapeReachable checks the exact key set of get_node_status.
func TestNodeStatusShapeReachable(t *testing.T) {
	srv := httptest.NewTLSServer(syncHandler("1.6.0"))
	defer srv.Close()
	host, port := hostPort(t, srv.URL)

	conn := newNodeDB(t)
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca)
		 VALUES (1, 'n1', ?, '', 'tcp', 1194, ?, 'k', 1, ?)`,
		host, port, certPEM(t, srv),
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}

	got := node.GetNodeStatus(conn, 1)
	if got == nil {
		t.Fatalf("GetNodeStatus = nil, want payload")
	}
	for _, key := range []string{"node", "node_info", "version_compat", "session_diagnostics", "latency_ms", "reachable", "tls_verified", "tls_mode", "cert_pin"} {
		if _, ok := got[key]; !ok {
			t.Errorf("payload missing key %q", key)
		}
	}
	if got["reachable"] != true {
		t.Errorf("reachable = %v, want true", got["reachable"])
	}
	if got["tls_mode"] != "verified" {
		t.Errorf("tls_mode = %v, want verified", got["tls_mode"])
	}
	info, _ := got["node_info"].(map[string]any)
	if info["version"] != "1.6.0" {
		t.Errorf("node_info.version = %v", info["version"])
	}
	vcompat, _ := got["version_compat"].(map[string]any)
	if vcompat["verdict"] != "compatible" {
		t.Errorf("version_compat.verdict = %v, want compatible", vcompat["verdict"])
	}
	pin, _ := got["cert_pin"].(map[string]any)
	if pin["pinned"] != true || pin["match"] != true {
		t.Errorf("cert_pin = %#v, want pinned+match", pin)
	}
}

// TestNodeStatusUnreachable: an unreachable node still returns the full shape
// with reachable=false and empty node_info.
func TestNodeStatusUnreachable(t *testing.T) {
	conn := newNodeDB(t)
	// 127.0.0.1:1 is a closed port; no pin so it fails closed fast.
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, tunnel_address, protocol, ovpn_port, port, key, status)
		 VALUES (2, 'dead', '127.0.0.1', '', 'tcp', 1194, 1, 'k', 1)`,
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "")

	got := node.GetNodeStatus(conn, 2)
	if got == nil {
		t.Fatalf("GetNodeStatus = nil, want payload for a known node")
	}
	if got["reachable"] != false {
		t.Errorf("reachable = %v, want false", got["reachable"])
	}
	if got["tls_verified"] != nil {
		t.Errorf("tls_verified = %v, want nil (never connected)", got["tls_verified"])
	}
	if got["tls_mode"] != "unknown" {
		t.Errorf("tls_mode = %v, want unknown", got["tls_mode"])
	}
	info, _ := got["node_info"].(map[string]any)
	if len(info) != 0 {
		t.Errorf("node_info = %#v, want empty", info)
	}
}

// TestNodeStatusMissing: an unknown id yields nil so the router can 404.
func TestNodeStatusMissing(t *testing.T) {
	conn := newNodeDB(t)
	if got := node.GetNodeStatus(conn, 99); got != nil {
		t.Fatalf("GetNodeStatus(99) = %#v, want nil", got)
	}
}

// TestUpdateConfigUnreachable: default (bool) mode returns false on failure.
func TestUpdateConfigUnreachable(t *testing.T) {
	c, err := node.NewClient("127.0.0.1", 1, "k", "", "", 5)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	if got := c.UpdateConfig(node.UpdateConfigParams{Protocol: "tcp", OVPNPort: 1194}); got != false {
		t.Fatalf("update_config = %#v, want false", got)
	}
}

// TestChunkBySize mirrors backend/node/fanout.chunk_by_size.
func TestChunkBySize(t *testing.T) {
	items := []int{1, 2, 3, 4, 5}
	one := func(int) int { return 1 }
	chunks := node.ChunkBySize(items, 2, 1000, one)
	if len(chunks) != 3 || len(chunks[0]) != 2 || len(chunks[2]) != 1 {
		t.Fatalf("chunks = %v, want sizes [2 2 1]", chunks)
	}
	// byte cap splits before the count cap (two 4-byte items fit in 10)
	big := func(int) int { return 4 }
	chunks = node.ChunkBySize(items, 100, 10, big)
	if len(chunks) != 3 {
		t.Fatalf("byte-capped chunks = %v, want 3", chunks)
	}
	// a single oversized item still forms its own chunk
	huge := func(int) int { return 999 }
	chunks = node.ChunkBySize(items, 100, 10, huge)
	if len(chunks) != 5 {
		t.Fatalf("oversized chunks = %v, want 5", chunks)
	}
}

// TestSyncAllUserLimitsEmptyShape pins the result keys for the no-node case.
func TestSyncAllUserLimitsEmptyShape(t *testing.T) {
	conn := newNodeDB(t)
	got := node.SyncAllUserLimits(conn)
	for _, key := range []string{"total", "success", "skipped", "applied", "results"} {
		if _, ok := got[key]; !ok {
			t.Errorf("result missing key %q: %#v", key, got)
		}
	}
	if got["total"] != 0 {
		t.Errorf("total = %v, want 0", got["total"])
	}
}

// TestPanelIDForMissingSettings returns empty rather than erroring.
func TestPanelIDForMissingSettings(t *testing.T) {
	conn := newNodeDB(t)
	if got := node.PanelIDFor(conn); got != "" {
		t.Errorf("PanelIDFor = %q, want empty", got)
	}
	if _, err := conn.Exec(`INSERT INTO settings (id, panel_id) VALUES (1, 'pid-1')`); err != nil {
		t.Fatalf("insert settings: %v", err)
	}
	if got := node.PanelIDFor(conn); got != "pid-1" {
		t.Errorf("PanelIDFor = %q, want pid-1", got)
	}
}
