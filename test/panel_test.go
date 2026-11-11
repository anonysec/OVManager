// Parity tests for Phase 4: the remaining routers (setting, security, tls,
// updater, maintenance, sub, plus the health overview/login endpoints).
//
// Each route is asserted on status + response shape against what the original
// routers returned (ResponseModel envelope vs plain JSON, and the 4xx shapes
// from the recent fail-closed/traversal fixes).
package tests

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
	"github.com/anonysec/OVManager/internal/node"
	"github.com/anonysec/OVManager/internal/panel"
	"github.com/anonysec/OVManager/internal/telemetry"
	"github.com/anonysec/OVManager/internal/users"
)

const panelSchema = `
DROP TABLE IF EXISTS Admin;
CREATE TABLE Admin (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
  is_owner BOOLEAN DEFAULT 0, telegram_id INTEGER);
DROP TABLE IF EXISTS Session;
CREATE TABLE Session (id INTEGER PRIMARY KEY, token_hash VARCHAR UNIQUE, username VARCHAR,
  role VARCHAR, created_at FLOAT, expires_at FLOAT, last_seen_at FLOAT,
  user_agent VARCHAR, ip VARCHAR);
DROP TABLE IF EXISTS Setting;
CREATE TABLE Setting (id INTEGER PRIMARY KEY, tunnel_address VARCHAR, port INTEGER DEFAULT 1194,
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
DROP TABLE IF EXISTS Node;
CREATE TABLE Node (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR, tunnel_address VARCHAR,
  protocol VARCHAR DEFAULT 'tcp', ovpn_port INTEGER DEFAULT 1194, port INTEGER DEFAULT 2083,
  key VARCHAR, status BOOLEAN DEFAULT 1, server_ca VARCHAR, country_code VARCHAR,
  latitude REAL, longitude REAL, extra_ports VARCHAR DEFAULT '', settings TEXT DEFAULT '{}');
DROP TABLE IF EXISTS User;
CREATE TABLE User (id INTEGER PRIMARY KEY, uuid VARCHAR UNIQUE, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, expiry_date DATE, is_active BOOLEAN DEFAULT 1,
  last_online DATETIME, tag VARCHAR);
CREATE TABLE IF NOT EXISTS Delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL,
  event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key));
DROP TABLE IF EXISTS UserNodeUsage;
CREATE TABLE UserNodeUsage (user_id INTEGER NOT NULL, node_id INTEGER NOT NULL, baseline INTEGER NOT NULL, epoch TEXT NOT NULL DEFAULT '', PRIMARY KEY (user_id, node_id));
DROP TABLE IF EXISTS UserTrafficDaily;
CREATE TABLE UserTrafficDaily (user_id INTEGER NOT NULL, day TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day));
`

// panelEnv is the isolated filesystem + PATH the panel server runs against.
type panelEnv struct {
	srv     *httptest.Server
	token   string
	conn    *sql.DB
	dataDir string
	appDir  string
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

	conn, err := db.Open(filepath.Join(dataDir, "app.db"))
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
	nodeH := node.NewHandler(svc)
	nodeH.OnNodeChange = func(op string) {
		telemetry.Publish("nodes", telemetry.KV{Key: "op", Val: op})
	}
	nodeH.Mount(inner)
	telemetry.NewHandler(svc).Mount(inner)
	h.Mount(inner)

	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	root.Handle("/", h.SubHandler())

	srv := httptest.NewServer(panel.SecurityHeaders(root))
	t.Cleanup(srv.Close)
	token := loginToken(t, srv.URL, "owner", knownPassword)
	if token == "" {
		t.Fatal("login returned no session token")
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

	// The backup routes need a database file at DATA_DIR/app.db, which is
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
		{name: "settings get", method: "GET", path: "/api/settings", wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"subscription_path", "subscription_url_prefix", "timezone", "panel_version",
				"bot_configured", "urlpath", "sub_profile_title", "sub_update_interval_hours",
				"auto_backup_time", "telegram_backup_available", "panel_id"}},
		{name: "settings timezone", method: "PUT", path: "/api/settings/timezone",
			body: map[string]any{"timezone": "UTC"}, wantStatus: 200, wantEnvelope: true,
			dataKeys: []string{"timezone"}, wantSuccess: boolPtr(true)},
		{name: "settings timezone invalid", method: "PUT", path: "/api/settings/timezone",
			body: map[string]any{"timezone": "Not/AZone"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "settings subscription", method: "PUT", path: "/api/settings/subscription",
			body:       map[string]any{"sub_announce": "hi", "sub_update_interval_hours": 24},
			wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(true),
			dataKeys: []string{"sub_announce", "sub_update_interval_hours"}},
		{name: "settings subscription bad hours", method: "PUT", path: "/api/settings/subscription",
			body: map[string]any{"sub_update_interval_hours": 999}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings subscription bad support url", method: "PUT", path: "/api/settings/subscription",
			body: map[string]any{"sub_support_url": "javascript:alert(1)"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings domain", method: "PUT", path: "/api/settings/domain",
			body: map[string]any{"panel_domain": "vpn.example.com"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"panel_domain"}},
		{name: "settings domain invalid", method: "PUT", path: "/api/settings/domain",
			body: map[string]any{"panel_domain": "http://vpn.example.com"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings bot", method: "PUT", path: "/api/settings/bot",
			body: map[string]any{"default_days": 45}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"default_days"}},
		{name: "settings bot bad backup time", method: "PUT", path: "/api/settings/bot",
			body: map[string]any{"auto_backup_time": "25:00"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "settings bot telegram without bot", method: "PUT", path: "/api/settings/bot",
			body: map[string]any{"telegram_backup_enabled": true}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false)},
		{name: "alerts test unknown channel", method: "POST", path: "/api/settings/alerts/test",
			body: map[string]any{"channel": "slack"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "alerts test telegram unconfigured", method: "POST", path: "/api/settings/alerts/test",
			body: map[string]any{"channel": "telegram"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(false), dataKeys: []string{"channel", "sent"}},
		{name: "settings urlpath", method: "PUT", path: "/api/settings/urlpath",
			body: map[string]any{"urlpath": "panel"}, wantStatus: 200, wantEnvelope: true,
			wantSuccess: boolPtr(true), dataKeys: []string{"urlpath", "panel_url"}},
		{name: "settings urlpath reserved", method: "PUT", path: "/api/settings/urlpath",
			body: map[string]any{"urlpath": "api"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "settings urlpath bad chars", method: "PUT", path: "/api/settings/urlpath",
			body: map[string]any{"urlpath": "a b"}, wantStatus: 200, wantEnvelope: true, wantSuccess: boolPtr(false)},
		{name: "server info", method: "GET", path: "/api/settings/info", wantStatus: 200, wantEnvelope: true,
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
			wantSuccess: boolPtr(true), dataKeys: []string{"removed", "removed_audit"}},

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
