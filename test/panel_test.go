// Parity tests for Phase 4: the remaining routers (setting, security, tls,
// updater, maintenance, sub, plus the health overview/login endpoints).
//
// Each route is asserted on status + response shape against what the original
// routers returned (ResponseModel envelope vs plain JSON, and the 4xx shapes
// from the recent fail-closed/traversal fixes).
package tests

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"database/sql"
	"encoding/json"
	"encoding/pem"
	"io"
	"math/big"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/panel"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	"github.com/anonysec/OVManager/go/internal/users"
)

// panelSchema mirrors the columns the Phase 4 routers touch (models.py +
// migrations/constants.py).
const panelSchema = `
DROP TABLE IF EXISTS admins;
CREATE TABLE admins (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
  is_owner BOOLEAN DEFAULT 0, telegram_id INTEGER);
DROP TABLE IF EXISTS sessions;
CREATE TABLE sessions (id INTEGER PRIMARY KEY, token_hash VARCHAR UNIQUE, username VARCHAR,
  role VARCHAR, created_at FLOAT, expires_at FLOAT, last_seen_at FLOAT,
  user_agent VARCHAR, ip VARCHAR);
DROP TABLE IF EXISTS settings;
CREATE TABLE settings (id INTEGER PRIMARY KEY, tunnel_address VARCHAR, port INTEGER DEFAULT 1194,
  protocol VARCHAR DEFAULT 'tcp', timezone VARCHAR DEFAULT 'UTC', bot_token VARCHAR,
  bot_enabled BOOLEAN DEFAULT 0, default_days INTEGER DEFAULT 30,
  default_traffic_gb INTEGER DEFAULT 100, default_max_users INTEGER DEFAULT 1,
  owner_telegram_id INTEGER, notify_expiry BOOLEAN DEFAULT 1, notify_traffic BOOLEAN DEFAULT 1,
  notify_node_down BOOLEAN DEFAULT 1, alert_days_left INTEGER DEFAULT 3,
  alert_usage_enabled BOOLEAN DEFAULT 1, alert_usage_pct INTEGER DEFAULT 80,
  alert_cpu_enabled BOOLEAN DEFAULT 1, alert_cpu_pct INTEGER DEFAULT 85,
  subscription_url_prefix VARCHAR, subscription_path VARCHAR DEFAULT 'sub',
  sub_profile_title VARCHAR DEFAULT 'OVManager VPN', sub_support_url VARCHAR DEFAULT '',
  sub_announce VARCHAR DEFAULT '', sub_update_interval_hours INTEGER DEFAULT 12,
  urlpath VARCHAR DEFAULT '', auto_backup_enabled BOOLEAN DEFAULT 0,
  auto_backup_time VARCHAR DEFAULT '03:30', auto_backup_keep INTEGER DEFAULT 50,
  offsite_backup_target VARCHAR, telegram_backup_enabled BOOLEAN DEFAULT 0,
  telegram_summary_time VARCHAR DEFAULT '09:00',
  ssl_cert_file VARCHAR, ssl_key_file VARCHAR, acme_domain VARCHAR, acme_email VARCHAR,
  cert_method VARCHAR DEFAULT 'selfsigned', panel_id VARCHAR, panel_url VARCHAR,
  panel_domain VARCHAR, bot_owner_setup_complete BOOLEAN DEFAULT 0);
DROP TABLE IF EXISTS nodes;
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR, tunnel_address VARCHAR,
  protocol VARCHAR DEFAULT 'tcp', ovpn_port INTEGER DEFAULT 1194, port INTEGER DEFAULT 2083,
  key VARCHAR, status BOOLEAN DEFAULT 1, server_ca VARCHAR, country_code VARCHAR,
  latitude REAL, longitude REAL);
DROP TABLE IF EXISTS users;
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR UNIQUE, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, expiry_date DATE, is_active BOOLEAN DEFAULT 1,
  last_online DATETIME, tag VARCHAR);
CREATE TABLE IF NOT EXISTS settings_kv (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at FLOAT);
CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL,
  event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key));
CREATE TABLE IF NOT EXISTS node_health_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  node_id INTEGER, node_name TEXT, cpu REAL, memory REAL, live_count INTEGER, latency_ms REAL,
  reachable INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS traffic_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  total_used REAL NOT NULL, active_connections INTEGER NOT NULL, online_users INTEGER NOT NULL,
  active_users INTEGER NOT NULL, total_users INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS security_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  auth_errors INTEGER NOT NULL, rejects INTEGER NOT NULL, stale_markers INTEGER NOT NULL,
  offline_nodes INTEGER NOT NULL, full_users INTEGER NOT NULL, inactive_users INTEGER NOT NULL);
DROP TABLE IF EXISTS user_traffic_daily;
CREATE TABLE user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day));
CREATE TABLE IF NOT EXISTS traffic_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  user_id INTEGER NOT NULL, node_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
  delta_bytes INTEGER NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (user_id, ts, kind, node_id));
`

// panelEnv is the isolated filesystem + PATH the panel server runs against.
type panelEnv struct {
	srv     *httptest.Server
	token   string
	conn    *sql.DB
	dataDir string
	appDir  string
	tlsKey  string
	tlsCert string
}

// newPanelEnv boots the whole API surface in a throwaway DATA_DIR.
//
// PATH points at an empty directory on purpose: the restart/update routes ask
// `which systemctl` / `which docker` / `which rsync` first, and this host has
// both plus a live ovmanager.service — without the stub PATH a parity test
// would restart (or update) the real panel. HOME is stubbed for the same
// reason: tls.renew looks for $HOME/.acme.sh/acme.sh, which a developer box
// running the panel really does have.
func newPanelEnv(t *testing.T) *panelEnv {
	t.Helper()
	dataDir := t.TempDir()
	appDir := t.TempDir()
	empty := t.TempDir()
	t.Setenv("DATA_DIR", dataDir)
	t.Setenv("PATH", empty)
	t.Setenv("HOME", empty)
	t.Setenv("OVM_APP_DIR", appDir)

	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(panelSchema); err != nil {
		t.Fatalf("panel schema: %v", err)
	}
	seedOwner(t, conn, "owner", bcryptHash)

	svc := auth.NewService(conn, dataDir)
	h := panel.NewHandler(svc)
	inner := http.NewServeMux()
	svc.Mount(inner)
	users.NewHandler(svc).Mount(inner)
	node.NewHandler(svc).Mount(inner)
	telemetry.NewHandler(svc).Mount(inner)
	h.Mount(inner)

	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	h.MountSub(root)

	srv := httptest.NewServer(panel.SecurityHeaders(root))
	t.Cleanup(srv.Close)
	token, _ := login(t, srv.URL, "owner", knownPassword)["access_token"].(string)
	if token == "" {
		t.Fatal("login returned no access_token")
	}
	return &panelEnv{srv: srv, token: token, conn: conn, dataDir: dataDir, appDir: appDir}
}

// rawReq performs a request and returns status, headers and the raw body.
func rawReq(t *testing.T, method, url, token string, body io.Reader, contentType string) (*http.Response, []byte) {
	t.Helper()
	req, err := http.NewRequest(method, url, body)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	defer res.Body.Close()
	raw, _ := io.ReadAll(res.Body)
	return res, raw
}

func jsonBody(t *testing.T, v any) io.Reader {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return bytes.NewReader(raw)
}

type panelCase struct {
	name         string
	method       string
	path         string
	body         any
	wantStatus   int
	wantEnvelope bool
	wantKeys     []string // top-level keys that must be present
	dataKeys     []string // envelope .data keys that must be present
	wantSuccess  *bool
	msgContains  string
}

func boolPtr(v bool) *bool { return &v }

// TestPanelSurface is the per-endpoint status/shape table for Phase 4.
func TestPanelSurface(t *testing.T) {
	env := newPanelEnv(t)

	// The backup routes need a database file at DATA_DIR/ovmanager.db, which is
	// the live test DB; create one backup so download/restore are reachable.
	pre := []panelCase{
		{name: "backup create", method: "POST", path: "/api/maintenance/backup", wantStatus: 200,
			wantEnvelope: true, dataKeys: []string{"filename", "path"}, wantSuccess: boolPtr(true)},
	}

	cases := []panelCase{
		// --- health router ---
		{name: "health overview", method: "GET", path: "/api/health/overview", wantStatus: 200,
			wantKeys: []string{"checks", "details"}},
		{name: "health login-health", method: "GET", path: "/api/health/login-health", wantStatus: 200,
			wantEnvelope: true},
		{name: "health login-diagnostics", method: "GET", path: "/api/health/login-diagnostics/nobody", wantStatus: 200,
			wantEnvelope: true},
		{name: "health setup", method: "GET", path: "/api/health/setup", wantStatus: 200,
			wantKeys: []string{"has_node", "has_user", "has_active_node", "node_count", "user_count"}},
		{name: "health tls", method: "GET", path: "/api/health/tls", wantStatus: 200,
			wantKeys: []string{"issued_by", "install_hint"}},

		// --- server/settings ---
		{name: "settings get", method: "GET", path: "/api/server/settings", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"subscription_path", "subscription_url_prefix", "timezone", "panel_version",
				"bot_configured", "urlpath", "sub_profile_title", "sub_update_interval_hours",
				"auto_backup_time", "telegram_backup_available", "panel_id"}},
		{name: "settings get slash", method: "GET", path: "/api/server/settings/", wantStatus: 200, wantEnvelope: true},
		{name: "settings timezone", method: "PUT", path: "/api/server/settings/timezone",
			body: map[string]any{"timezone": "UTC"}, wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"timezone"}, wantSuccess: boolPtr(true)},
		{name: "settings timezone invalid", method: "PUT", path: "/api/server/settings/timezone",
			body: map[string]any{"timezone": "Not/AZone"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "settings subscription", method: "PUT", path: "/api/server/settings/subscription",
			body:       map[string]any{"sub_announce": "hi", "sub_update_interval_hours": 24},
			wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(true),
			dataKeys: []string{"sub_announce", "sub_update_interval_hours"}},
		{name: "settings subscription bad hours", method: "PUT", path: "/api/server/settings/subscription",
			body: map[string]any{"sub_update_interval_hours": 999}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings subscription bad support url", method: "PUT", path: "/api/server/settings/subscription",
			body: map[string]any{"sub_support_url": "javascript:alert(1)"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings domain", method: "PUT", path: "/api/server/settings/domain",
			body: map[string]any{"panel_domain": "vpn.example.com"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"panel_domain"}},
		{name: "settings domain invalid", method: "PUT", path: "/api/server/settings/domain",
			body: map[string]any{"panel_domain": "http://vpn.example.com"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings bot", method: "PUT", path: "/api/server/settings/bot",
			body: map[string]any{"default_days": 45}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"default_days"}},
		{name: "settings bot bad backup time", method: "PUT", path: "/api/server/settings/bot",
			body: map[string]any{"auto_backup_time": "25:00"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings bot telegram without bot", method: "PUT", path: "/api/server/settings/bot",
			body: map[string]any{"telegram_backup_enabled": true}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "alerts test unknown channel", method: "POST", path: "/api/server/alerts/test",
			body: map[string]any{"channel": "slack"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "alerts test telegram unconfigured", method: "POST", path: "/api/server/alerts/test",
			body: map[string]any{"channel": "telegram"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), dataKeys: []string{"channel", "sent"}},
		{name: "settings urlpath", method: "PUT", path: "/api/server/settings/urlpath",
			body: map[string]any{"urlpath": "panel"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"urlpath", "panel_url"}},
		{name: "settings urlpath reserved", method: "PUT", path: "/api/server/settings/urlpath",
			body: map[string]any{"urlpath": "api"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "settings urlpath bad chars", method: "PUT", path: "/api/server/settings/urlpath",
			body: map[string]any{"urlpath": "a b"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "server info", method: "GET", path: "/api/server/info", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"cpu", "memory_total", "memory_used", "memory_percent", "disk_total",
				"disk_used", "disk_percent", "uptime"}},

		// --- security ---
		{name: "security summary", method: "GET", path: "/api/security/summary", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"hours", "timezone", "auth_errors", "policy_rejects", "per_node", "events",
				"ongoing_users", "unclassified_nodes", "last_errors", "top_common_names"}},

		// --- maintenance ---
		{name: "backup list", method: "GET", path: "/api/maintenance/backup/list", wantStatus: 200, wantEnvelope: true},
		{name: "backup download", method: "GET", path: "/api/maintenance/backup/download", wantStatus: 200,
			wantKeys: nil},
		{name: "sync limits", method: "POST", path: "/api/maintenance/sync-limits", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(true)},
		{name: "clean stale", method: "POST", path: "/api/maintenance/clean-stale", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(true)},
		{name: "restart panel", method: "POST", path: "/api/maintenance/restart", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(false), dataKeys: []string{"restarted"}},
		{name: "cleanup preview", method: "POST", path: "/api/maintenance/cleanup/preview",
			body: map[string]any{"status": "expired", "older_than_days": 0}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"status", "matched", "sample", "truncated", "total_users"}},
		{name: "cleanup run unconfirmed", method: "POST", path: "/api/maintenance/cleanup/run",
			body: map[string]any{"status": "expired"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "usage reset-all unconfirmed", method: "POST", path: "/api/maintenance/usage/reset-all",
			body: map[string]any{}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "usage reset-all confirmed", method: "POST", path: "/api/maintenance/usage/reset-all",
			body: map[string]any{"confirm": true}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"reset"}},
		{name: "usage purge unconfirmed", method: "POST", path: "/api/maintenance/usage/purge",
			body: map[string]any{}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "usage purge confirmed", method: "POST", path: "/api/maintenance/usage/purge",
			body: map[string]any{"older_than_days": 90, "confirm": true}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"removed", "removed_ledger"}},

		// --- tls ---
		{name: "tls settings", method: "GET", path: "/api/tls/settings", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"fields", "methods", "restart_required"}},
		{name: "tls settings bad method", method: "PUT", path: "/api/tls/settings",
			body: map[string]any{"cert_method": "bogus"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "tls settings bad domain", method: "PUT", path: "/api/tls/settings",
			body: map[string]any{"acme_domain": "not a domain"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "tls settings bad email", method: "PUT", path: "/api/tls/settings",
			body: map[string]any{"acme_email": "nope"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "tls settings traversal rejected", method: "PUT", path: "/api/tls/settings",
			body: map[string]any{"key_file": "../../etc/passwd"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), msgContains: "must not contain '..'"},
		{name: "tls status", method: "GET", path: "/api/tls/status", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"mode", "source", "cert_path", "expires_days", "names", "fingerprint_sha256",
				"issued_by", "restart_required", "previous_available"}},
		{name: "tls rollback none", method: "POST", path: "/api/tls/rollback", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "tls restart", method: "POST", path: "/api/tls/restart", wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), dataKeys: []string{"restart_required", "restarted"}},
		{name: "tls renew no domain", method: "POST", path: "/api/tls/renew",
			body: map[string]any{}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "tls renew bad domain", method: "POST", path: "/api/tls/renew",
			body: map[string]any{"domain": "not a domain"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), msgContains: "not valid"},
		{name: "tls renew missing email", method: "POST", path: "/api/tls/renew",
			body: map[string]any{"domain": "vpn.example.com"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), msgContains: "contact email address is required"},
		{name: "https status alias", method: "GET", path: "/api/https/status", wantStatus: 200, wantEnvelope: true},

		// --- updater ---
		{name: "updater operation no state", method: "GET", path: "/api/updater/operation", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(true)},
		{name: "updater run no installer", method: "POST", path: "/api/updater/run", wantStatus: 200,
			wantEnvelope: true, wantSuccess: boolPtr(false), dataKeys: []string{"mode", "command", "restart_command"}},
	}

	run := func(c panelCase) {
		t.Helper()
		var body io.Reader
		if c.body != nil {
			body = jsonBody(t, c.body)
		}
		res, raw := rawReq(t, c.method, env.srv.URL+c.path, env.token, body, "application/json")
		if res.StatusCode != c.wantStatus {
			t.Fatalf("%s %s: status = %d, want %d (body %s)", c.method, c.path, res.StatusCode, c.wantStatus, raw)
		}
		if c.name == "backup download" {
			if ct := res.Header.Get("Content-Type"); !strings.Contains(ct, "application/octet-stream") {
				t.Fatalf("backup download content-type = %q", ct)
			}
			return
		}
		var got map[string]any
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatalf("%s %s: decode: %v (body %s)", c.method, c.path, err, raw)
		}
		for _, k := range c.wantKeys {
			if _, ok := got[k]; !ok {
				t.Fatalf("%s %s: missing key %q in %s", c.method, c.path, k, raw)
			}
		}
		if c.wantEnvelope {
			for _, k := range []string{"success", "msg"} {
				if _, ok := got[k]; !ok {
					t.Fatalf("%s %s: envelope missing %q in %s", c.method, c.path, k, raw)
				}
			}
		}
		if c.wantSuccess != nil {
			if v, _ := got["success"].(bool); v != *c.wantSuccess {
				t.Fatalf("%s %s: success = %v, want %v (body %s)", c.method, c.path, got["success"], *c.wantSuccess, raw)
			}
		}
		if c.msgContains != "" {
			msg, _ := got["msg"].(string)
			if !strings.Contains(msg, c.msgContains) {
				t.Fatalf("%s %s: msg = %q, want it to contain %q", c.method, c.path, msg, c.msgContains)
			}
		}
		for _, k := range c.dataKeys {
			data, _ := got["data"].(map[string]any)
			if data == nil {
				t.Fatalf("%s %s: data is not an object in %s", c.method, c.path, raw)
			}
			if _, ok := data[k]; !ok {
				t.Fatalf("%s %s: data missing %q in %s", c.method, c.path, k, raw)
			}
		}
	}

	for _, c := range pre {
		run(c)
	}
	for _, c := range cases {
		if c.name == "updater run no installer" {
			// Updater's app dir differs from APPDIR: it defaults to
			// /opt/ovmanager, where this host really does have install.sh.
			t.Setenv("OVM_APP_DIR", t.TempDir())
		}
		run(c)
	}
}

// TestMaintenanceRestoreRoundTrip drives the form-based restore of a stored
// backup, including the "backup file must be .db" guard.
func TestMaintenanceRestoreRoundTrip(t *testing.T) {
	env := newPanelEnv(t)
	run := func(form url.Values) (*http.Response, map[string]any) {
		res, raw := rawReq(t, "POST", env.srv.URL+"/api/maintenance/backup/restore", env.token,
			strings.NewReader(form.Encode()), "application/x-www-form-urlencoded")
		var got map[string]any
		_ = json.Unmarshal(raw, &got)
		return res, got
	}

	res, got := run(url.Values{})
	if res.StatusCode != 200 || got["success"] != false {
		t.Fatalf("restore without file: %d %v", res.StatusCode, got)
	}
	if msg, _ := got["msg"].(string); msg != "Backup file must be a .db file" {
		t.Fatalf("restore without file msg = %q", msg)
	}

	if _, raw := rawReq(t, "POST", env.srv.URL+"/api/maintenance/backup", env.token, nil, ""); len(raw) == 0 {
		t.Fatal("backup create returned no body")
	}
	entries, err := os.ReadDir(filepath.Join(env.dataDir, "backups"))
	if err != nil || len(entries) == 0 {
		t.Fatalf("no backup written: %v", err)
	}
	name := entries[0].Name()
	if !strings.HasSuffix(name, ".db") {
		t.Fatalf("backup name = %q", name)
	}

	res, got = run(url.Values{"restore_from_server": {name}})
	if res.StatusCode != 200 || got["success"] != true {
		t.Fatalf("restore from server: %d %v", res.StatusCode, got)
	}
	data, _ := got["data"].(map[string]any)
	if data["rolled_back"] != false {
		t.Fatalf("restore data = %v", data)
	}

	// Traversal out of the backup directory is refused, not resolved.
	_, got = run(url.Values{"restore_from_server": {"../../etc/passwd"}})
	if got["success"] != false {
		t.Fatalf("traversal restore accepted: %v", got)
	}
}

// mintPair renders a matching ECDSA key + self-signed certificate in PEM.
func mintPair(t *testing.T, cn string) (keyPEM, certPEM string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(90 * 24 * time.Hour),
		DNSNames:     []string{cn},
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatalf("marshal key: %v", err)
	}
	keyPEM = string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}))
	certPEM = string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}))
	return keyPEM, certPEM
}

// postPair uploads a key + certificate pair to path as multipart form data.
func postPair(t *testing.T, url, token, path, keyPEM, certPEM string) (*http.Response, []byte) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for field, content := range map[string]string{"key": keyPEM, "cert": certPEM} {
		part, err := mw.CreateFormFile(field, field+".pem")
		if err != nil {
			t.Fatalf("form file: %v", err)
		}
		if _, err := part.Write([]byte(content)); err != nil {
			t.Fatalf("write part: %v", err)
		}
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	return rawReq(t, "POST", url+path, token, &buf, mw.FormDataContentType())
}

// TestTLSUploadValidatesAndActivates covers the upload path: validation
// failures keep the previous pair, a valid pair is written at the declared
// paths (0600/0644) and rollback restores the previous one.
func TestTLSUploadValidatesAndActivates(t *testing.T) {
	env := newPanelEnv(t)
	keyPath := filepath.Join(env.dataDir, "declared", "privkey.pem")
	certPath := filepath.Join(env.dataDir, "declared", "fullchain.pem")
	t.Setenv("SSL_KEYFILE", keyPath)
	t.Setenv("SSL_CERTFILE", certPath)

	key1, cert1 := mintPair(t, "one.example.com")
	res, raw := postPair(t, env.srv.URL, env.token, "/api/tls/upload", key1, cert1)
	if res.StatusCode != 200 || !strings.Contains(string(raw), `"success":true`) {
		t.Fatalf("upload valid pair: %d %s", res.StatusCode, raw)
	}
	info, err := os.Stat(keyPath)
	if err != nil {
		t.Fatalf("declared key not written: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("key mode = %v, want 0600", info.Mode().Perm())
	}
	if info, err = os.Stat(certPath); err != nil {
		t.Fatalf("declared cert not written: %v", err)
	}

	// A mismatched pair is refused and must not disturb the active pair.
	otherKey, otherCert := mintPair(t, "two.example.com")
	_, raw = postPair(t, env.srv.URL, env.token, "/api/tls/upload", otherKey, cert1)
	if !strings.Contains(string(raw), "does not match the certificate") {
		t.Fatalf("mismatched pair not rejected: %s", raw)
	}

	// Garbage PEM is refused with the exact wording.
	_, raw = postPair(t, env.srv.URL, env.token, "/api/tls/upload", "not a key", "not a cert")
	if !strings.Contains(string(raw), "not a valid PEM private key") {
		t.Fatalf("garbage pair not rejected: %s", raw)
	}

	// A second valid pair activates, retaining the first as the previous one
	// (the backup only happens once a pair is already installed).
	res, raw = postPair(t, env.srv.URL, env.token, "/api/tls/upload", otherKey, otherCert)
	if res.StatusCode != 200 || !strings.Contains(string(raw), `"success":true`) {
		t.Fatalf("second upload: %d %s", res.StatusCode, raw)
	}

	// Status now reports the declared pair, and rollback restores pair one.
	res, raw = rawReq(t, "GET", env.srv.URL+"/api/tls/status", env.token, nil, "")
	if !strings.Contains(string(raw), `"mode":"managed"`) {
		t.Fatalf("tls status after upload: %s", raw)
	}
	res, raw = rawReq(t, "POST", env.srv.URL+"/api/tls/rollback", env.token, nil, "")
	if res.StatusCode != 200 || !strings.Contains(string(raw), `"success":true`) {
		t.Fatalf("rollback: %d %s", res.StatusCode, raw)
	}
	if restored, err := os.ReadFile(keyPath); err != nil || string(restored) != key1 {
		t.Fatalf("rollback did not restore pair one (err=%v)", err)
	}

	// Self-signed generation lands at the same declared paths.
	res, raw = rawReq(t, "POST", env.srv.URL+"/api/tls/self-signed", env.token, nil, "")
	if res.StatusCode != 200 || !strings.Contains(string(raw), `"success":true`) {
		t.Fatalf("self-signed: %d %s", res.StatusCode, raw)
	}
	// https_router aliases share the same handlers.
	if res, raw = postPair(t, env.srv.URL, env.token, "/api/https/existing", key1, cert1); res.StatusCode != 200 {
		t.Fatalf("https/existing alias: %d %s", res.StatusCode, raw)
	}
}

// TestUpdaterStateMachine pins the /operation shape for every persisted phase.
func TestUpdaterStateMachine(t *testing.T) {
	env := newPanelEnv(t)
	statePath := filepath.Join(env.dataDir, "update-state.json")

	// No state file: success true, data null.
	_, raw := rawReq(t, "GET", env.srv.URL+"/api/updater/operation", env.token, nil, "")
	var got map[string]any
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["success"] != true || got["data"] != nil {
		t.Fatalf("no-state operation = %v", got)
	}

	state := map[string]any{
		"phase": "staged", "from_version": "1.5.0", "to_version": "1.6.0",
		"safety_backup": "ovmanager-pre-update-1.db", "updated_at": "2026-10-16T00:00:00Z", "pid": 42,
	}
	blob, _ := json.Marshal(state)
	if err := os.WriteFile(statePath, blob, 0o600); err != nil {
		t.Fatalf("write state: %v", err)
	}
	_, raw = rawReq(t, "GET", env.srv.URL+"/api/updater/operation", env.token, nil, "")
	_ = json.Unmarshal(raw, &got)
	data, _ := got["data"].(map[string]any)
	for _, k := range []string{"phase", "from_version", "to_version", "safety_backup", "updated_at", "pid",
		"maintenance", "finished"} {
		if _, ok := data[k]; !ok {
			t.Fatalf("operation data missing %q: %s", k, raw)
		}
	}
	if data["finished"] != false || data["maintenance"] != false {
		t.Fatalf("staged state = %v", data)
	}

	// update-maintenance marker present → maintenance true while running.
	if err := os.WriteFile(filepath.Join(env.dataDir, "update-maintenance"), []byte(""), 0o600); err != nil {
		t.Fatalf("write marker: %v", err)
	}
	state["phase"] = "committed"
	blob, _ = json.Marshal(state)
	_ = os.WriteFile(statePath, blob, 0o600)
	_, raw = rawReq(t, "GET", env.srv.URL+"/api/updater/operation", env.token, nil, "")
	_ = json.Unmarshal(raw, &got)
	data, _ = got["data"].(map[string]any)
	if data["finished"] != true || data["maintenance"] != true {
		t.Fatalf("committed state = %v", data)
	}

	// Unreadable state file: success false, data null.
	if err := os.WriteFile(statePath, []byte("{not json"), 0o600); err != nil {
		t.Fatalf("write bad state: %v", err)
	}
	_, raw = rawReq(t, "GET", env.srv.URL+"/api/updater/operation", env.token, nil, "")
	_ = json.Unmarshal(raw, &got)
	if got["success"] != false || got["data"] != nil {
		t.Fatalf("bad-state operation = %v", got)
	}
}

// TestPanelRequiresOwner pins the 401/403 gate on the owner-only routes.
func TestPanelRequiresOwner(t *testing.T) {
	env := newPanelEnv(t)
	for _, path := range []string{
		"/api/health/overview", "/api/server/settings", "/api/tls/status",
		"/api/updater/operation", "/api/security/summary", "/api/maintenance/backup/list",
	} {
		res, _ := rawReq(t, "GET", env.srv.URL+path, "", nil, "")
		if res.StatusCode != 401 {
			t.Fatalf("GET %s without token: status = %d, want 401", path, res.StatusCode)
		}
	}
}

var _ = time.Now
