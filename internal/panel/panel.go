// Package panel ports the remaining routers (Phase 4): health overview,
// panel settings, security summary, TLS management, updater, maintenance and
// the subscription page.
//
// Configuration mirrors backend config: process environment first, the
// panel's .env second (pydantic-settings precedence). The .env is read from
// OVM_APP_DIR — install.sh chdirs to APP_DIR before exec — falling back to the
// working directory.
package panel

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/node"
)

// Handler serves the Phase 4 routes.
type Handler struct {
	Svc       *auth.Service
	startedAt time.Time

	// urlpath cache (backend/urlpath, 5s TTL). Per-handler rather
	// than process-global: observable behaviour is identical for the single
	// panel process, and it keeps tests hermetic.
	urlMu    sync.Mutex
	urlValue string
	urlAt    float64

	// issuance (bundle: the whole ACME flow owns the certificate state for
	// its duration) is serialized separately from the short file writes.
	acmeMu sync.Mutex

	// activeReq tracks in-flight requests so a database restore can wait for
	// them to complete before swapping the live pool.
	activeReq sync.WaitGroup
}

// TrackActive wraps a handler to track in-flight requests for the
// database restore drain. The restore path waits for activeReq to reach
// zero before closing the old pool, so in-flight requests see a live
// connection and don't hit "database is closed".
func (h *Handler) TrackActive(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h.activeReq.Add(1)
		defer h.activeReq.Done()
		next.ServeHTTP(w, r)
	})
}

// NewHandler builds the router over the shared auth service.
func NewHandler(svc *auth.Service) *Handler {
	return &Handler{Svc: svc, startedAt: time.Now()}
}

// Mount registers the Phase 4 routes relative to the caller's prefix (app
// includes every router under /api).
func (h *Handler) Mount(mux *http.ServeMux) {
	owner := h.Svc.RequireOwner
	mux.HandleFunc("GET /health/overview", owner(h.healthOverview))
	mux.HandleFunc("GET /health/login-health", owner(h.loginHealth))
	mux.HandleFunc("GET /health/login-diagnostics/{username}", owner(h.loginDiagnostics))
	mux.HandleFunc("GET /health/setup", owner(h.healthSetup))
	mux.HandleFunc("GET /health/tls", owner(h.healthTLS))

	mux.HandleFunc("GET /settings", owner(h.getSettings))
	mux.HandleFunc("PUT /settings/timezone", owner(h.updateTimezone))
	mux.HandleFunc("PUT /settings/subscription", owner(h.updateSubscription))
	mux.HandleFunc("PUT /settings/domain", owner(h.updateDomain))
	mux.HandleFunc("PUT /settings/bot", owner(h.updateBotConfig))
	mux.HandleFunc("PUT /settings/urlpath", owner(h.updateURLPath))
	mux.HandleFunc("POST /settings/alerts/test", owner(h.testAlert))
	mux.HandleFunc("GET /settings/info", owner(h.serverInfo))

	// /server/* aliases for backwards compatibility with frontend / legacy router
	mux.HandleFunc("GET /server/settings", owner(h.getSettings))
	mux.HandleFunc("PUT /server/settings/timezone", owner(h.updateTimezone))
	mux.HandleFunc("PUT /server/settings/subscription", owner(h.updateSubscription))
	mux.HandleFunc("PUT /server/settings/domain", owner(h.updateDomain))
	mux.HandleFunc("PUT /server/settings/bot", owner(h.updateBotConfig))
	mux.HandleFunc("PUT /server/settings/urlpath", owner(h.updateURLPath))
	mux.HandleFunc("POST /server/settings/alerts/test", owner(h.testAlert))
	mux.HandleFunc("GET /server/info", owner(h.serverInfo))

	mux.HandleFunc("GET /security/summary", owner(h.securitySummary))

	mux.HandleFunc("GET /maintenance/backup/list", owner(h.backupList))
	mux.HandleFunc("GET /maintenance/backup/download", owner(h.backupDownload))
	mux.HandleFunc("POST /maintenance/backup", owner(h.backupCreate))
	mux.HandleFunc("POST /maintenance/backup/restore", owner(h.backupRestore))
	mux.HandleFunc("POST /maintenance/sync-limits", owner(h.syncLimits))
	mux.HandleFunc("POST /maintenance/sync-traffic", owner(h.syncTraffic))
	mux.HandleFunc("POST /maintenance/clean-stale", owner(h.cleanStale))
	mux.HandleFunc("POST /maintenance/restart", owner(h.restartPanel))
	mux.HandleFunc("POST /maintenance/cleanup/preview", owner(h.cleanupPreview))
	mux.HandleFunc("POST /maintenance/cleanup/run", owner(h.cleanupRun))
	mux.HandleFunc("POST /maintenance/usage/reset-all", owner(h.usageResetAll))
	mux.HandleFunc("POST /maintenance/usage/purge", owner(h.usagePurge))

	// TLS certificate management lives in the `ovmanager tls` CLI now. The ACME
	// renewal worker below still runs (it uses internal/acme directly).

	mux.HandleFunc("GET /updater/status", owner(h.updateStatus))
	mux.HandleFunc("GET /updater/operation", owner(h.updateOperation))
	mux.HandleFunc("POST /updater/run", owner(h.runUpdate))

	// Daily ACME renewal (T-30d) + boot issuance when the installer wired
	// OVM_ACME_DOMAIN. No-op without an enrolled domain.
	h.startACMEWorker()

	// Per-user traffic accounting: one goroutine polling active nodes and
	// billing their cumulative-total deltas. Runs regardless of the Telegram
	// bot state.
	h.startTrafficWorker()

	// Live snapshot collector: one goroutine refreshing the connection/node
	// snapshot the subscription page, health checklist and SSE events read.
	// Idle cadence is enforced by the collector's own pollDue gate.
	h.startLiveWorker()

	// Telegram ops channel: one worker goroutine (daily summary at
	// telegram_summary_time, immediate expired/over-quota events, node/CPU
	// threshold sweeps through telemetry.CollectMetrics). No-op while the bot
	// is disabled or unconfigured.
	h.startTelegramWorker()
}

// MountSub registers the subscription page at /<SUBSCRIPTION_PATH>, outside
// the /api prefix (app includes that router unprefixed).
func (h *Handler) MountSub(mux *http.ServeMux) {
	prefix := "/" + subscriptionPath()
	mux.HandleFunc("GET "+prefix+"/static/subscription.js", h.subStaticJS)
	mux.HandleFunc("GET "+prefix+"/download/{uuid}/{node_name}", h.subDownload)
	mux.HandleFunc("GET "+prefix+"/{uuid}", h.subPage)
}

// --- configuration (backend) ---

// appDir is where .env and frontend/ live.
func appDir() string {
	if d := os.Getenv("OVM_APP_DIR"); d != "" {
		return d
	}
	if wd, err := os.Getwd(); err == nil {
		return wd
	}
	return "."
}

// dataDir resolves DATA_DIR per call so tests can point it at a temp dir.
func dataDir() string {
	if d := os.Getenv("DATA_DIR"); d != "" {
		return d
	}
	return node.DataDir
}

// envFileCache memoizes the last .env read (5s TTL, same cadence as the
// urlpath cache): the file is re-read at most every 5 seconds, keyed on the
// app dir so tests and callers swapping OVM_APP_DIR stay fresh.
var envFileCache = struct {
	mu     sync.Mutex
	dir    string
	at     time.Time
	values map[string]string
}{}

// invalidateEnvFileCache clears the .env cache so the next envFileValues call
// re-reads the file. Called after settings are written.
func invalidateEnvFileCache() {
	envFileCache.mu.Lock()
	defer envFileCache.mu.Unlock()
	envFileCache.values = nil
	envFileCache.dir = ""
}

// envFileValues reads the uncommented KEY=VALUE pairs from the panel's .env.
// The file is optional: an unreadable or missing one yields an empty map.
func envFileValues() map[string]string {
	dir := appDir()
	envFileCache.mu.Lock()
	defer envFileCache.mu.Unlock()
	if envFileCache.values != nil && envFileCache.dir == dir &&
		time.Since(envFileCache.at) < 5*time.Second {
		return envFileCache.values
	}
	values := map[string]string{}
	raw, err := os.ReadFile(filepath.Join(dir, ".env")) // #nosec G304 // triaged intentional
	if err == nil {
		for _, line := range strings.Split(string(raw), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
				continue
			}
			key, value, _ := strings.Cut(line, "=")
			values[strings.TrimSpace(key)] = strings.Trim(strings.TrimSpace(value), "'\"")
		}
	}
	envFileCache.dir, envFileCache.at, envFileCache.values = dir, time.Now(), values
	return values
}

// envOrFile is pydantic-settings precedence: a real environment variable wins
// over the .env line.
// TrustedProxyEnabled reports whether the panel sits behind a trusted
// reverse proxy. The panel's own auth service reads the same flag from the
// process environment; this reads it the way every other panel setting is
// read — process environment first, then the .env file — so a panel started
// by hand next to its .env behaves like a systemd or container one.
func TrustedProxyEnabled() bool {
	return strings.EqualFold(strings.TrimSpace(envOrFile("TRUSTED_PROXY")), "true")
}

func envOrFile(key string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return envFileValues()[key]
}

// sslKeyPath / sslCertPath are tls_paths.key_path / cert_path.
func sslKeyPath() string {
	if v := envOrFile("SSL_KEYFILE"); v != "" {
		return v
	}
	return filepath.Join(dataDir(), "tls", "privkey.pem")
}

func sslCertPath() string {
	if v := envOrFile("SSL_CERTFILE"); v != "" {
		return v
	}
	return filepath.Join(dataDir(), "tls", "fullchain.pem")
}

// SSLCertPath / SSLKeyPath are the exported forms used by cmd/main to decide
// binding and TLS mode.
func SSLCertPath() string { return sslCertPath() }
func SSLKeyPath() string  { return sslKeyPath() }

func subscriptionPath() string {
	if v := strings.Trim(envOrFile("SUBSCRIPTION_PATH"), "/"); v != "" {
		return v
	}
	return "sub"
}

func serverHost() string {
	for _, k := range []string{"HOST", "UVICORN_HOST"} {
		if v := envOrFile(k); v != "" {
			return v
		}
	}
	return "0.0.0.0"
}

func serverPort() int {
	for _, k := range []string{"PORT", "UVICORN_PORT"} {
		if v := envOrFile(k); v != "" {
			if n, err := strconv.Atoi(v); err == nil {
				return n
			}
		}
	}
	return 2095
}

// --- settings row (backend) ---

// settings is the single settings row as a column->value map. Column names
// come from the schema, not from user input, so building UPDATE statements
// from them is safe.
type settings map[string]any

func (s settings) str(key, def string) string {
	if v, ok := s[key].(string); ok && v != "" {
		return v
	}
	return def
}

// strOr is the raw DB value ("" for NULL).
func (s settings) strOr(key string) string {
	v, _ := s[key].(string)
	return v
}

// nullStr is the raw DB value, None when NULL.
func (s settings) nullStr(key string) any {
	if v, ok := s[key].(string); ok && v != "" {
		return v
	}
	return nil
}

func (s settings) num(key string, def int) int {
	switch v := s[key].(type) {
	case int64:
		return int(v)
	case float64:
		return int(v)
	}
	return def
}

// numOrNull is the nullable-int accessor for ints.
func (s settings) numOrNull(key string) any {
	switch v := s[key].(type) {
	case int64:
		return v
	case float64:
		return int64(v)
	}
	return nil
}

func (s settings) boolean(key string, def bool) bool {
	switch v := s[key].(type) {
	case int64:
		return v != 0
	case bool:
		return v
	}
	return def
}

// intOr is the int accessor with default for the alert thresholds:
// an unparsable value falls back, it is not treated as absent.
func (s settings) intOr(key string, def int) int {
	switch v := s[key].(type) {
	case int64:
		return int(v)
	case float64:
		return int(v)
	case string:
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func (h *Handler) settings() settings {
	return readSettings(h.Svc.DB())
}

// readSettings loads the single settings row, creating it when absent
// (crud.get_settings).
func readSettings(db *sql.DB) settings {
	var count int
	_ = db.QueryRow(`SELECT COUNT(*) FROM settings`).Scan(&count)
	if count == 0 {
		_, _ = db.Exec(`INSERT INTO settings (port, protocol) VALUES (1194, 'tcp')`)
	}
	rows, err := db.Query(`SELECT * FROM settings ORDER BY id LIMIT 1`)
	if err != nil {
		return settings{}
	}
	defer rows.Close()
	if !rows.Next() {
		return settings{}
	}
	cols, err := rows.Columns()
	if err != nil {
		return settings{}
	}
	vals := make([]any, len(cols))
	ptrs := make([]any, len(cols))
	for i := range vals {
		ptrs[i] = &vals[i]
	}
	if err := rows.Scan(ptrs...); err != nil {
		return settings{}
	}
	out := settings{}
	for i, c := range cols {
		out[c] = vals[i]
	}
	return out
}

// setColumns writes each column on the settings row.
func setColumns(db *sql.DB, values map[string]any) error {
	if len(values) == 0 {
		return nil
	}
	// Whitelist of valid settings columns to prevent SQL injection via dynamic column names.
	// Derived from the mappedColumns in internal/db/migrate.go.
	validColumns := map[string]bool{
		"tunnel_address": true, "port": true, "protocol": true, "timezone": true,
		"bot_token": true, "bot_enabled": true, "default_days": true,
		"default_traffic_gb": true, "default_max_users": true, "owner_telegram_id": true,
		"notify_expiry": true, "notify_traffic": true, "notify_node_down": true,
		"alert_days_left": true, "alert_usage_enabled": true, "alert_usage_pct": true,
		"alert_cpu_enabled": true, "alert_cpu_pct": true, "subscription_url_prefix": true,
		"subscription_path": true, "sub_profile_title": true, "sub_support_url": true,
		"sub_announce": true, "sub_update_interval_hours": true, "urlpath": true,
		"auto_backup_enabled": true, "auto_backup_time": true, "auto_backup_keep": true,
		"offsite_backup_target": true, "telegram_backup_enabled": true, "telegram_summary_time": true,
		"ssl_cert_file": true, "ssl_key_file": true, "acme_domain": true,
		"acme_email": true, "cert_method": true, "panel_id": true, "panel_url": true,
		"panel_domain": true, "bot_owner_setup_complete": true,
	}
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	for key, value := range values {
		if !validColumns[key] {
			_ = tx.Rollback()
			return fmt.Errorf("invalid settings column: %s", key)
		}
		if _, err := tx.Exec(`UPDATE settings SET `+key+` = ? WHERE id = (SELECT MIN(id) FROM settings)`, value); err != nil { // #nosec // key validated against allowlist above
			_ = tx.Rollback()
			return err
		}
	}
	if err := tx.Commit(); err != nil {
		_ = tx.Rollback()
		return err
	}
	// Invalidate .env cache so subsequent envFileValues reads pick up the new values immediately.
	invalidateEnvFileCache()
	return nil
}

// --- HTTP helpers ---

func envelope(w http.ResponseWriter, success bool, msg string, data any) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: success, Msg: msg, Data: data})
}

func plain(w http.ResponseWriter, body any) {
	auth.WriteJSON(w, http.StatusOK, body)
}

// decodeBody reads a JSON body; a malformed one is a 422 like FastAPI's.
func decodeBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		auth.WriteJSON(w, http.StatusUnprocessableEntity, map[string]any{
			"detail": []map[string]any{{
				"type": "json_invalid", "loc": []any{"body"}, "msg": "JSON decode error",
			}},
		})
		return false
	}
	return true
}

func (h *Handler) clientIP(r *http.Request) string {
	return auth.ClientIP(h.Svc.TrustedProxy, r)
}

// baseURL is FastAPI's str(request.base_url), using the externally visible
// scheme only when X-Forwarded-Proto comes from a configured trusted proxy.
func baseURL(r *http.Request) string {
	scheme := "http"
	if externallySecure(r) {
		scheme = "https"
	}
	return scheme + "://" + r.Host + "/"
}

func externallySecure(r *http.Request) bool {
	if r.TLS != nil {
		return true
	}
	if !TrustedProxyEnabled() {
		return false
	}
	forwarded := r.Header.Get("X-Forwarded-Proto")
	if i := strings.IndexByte(forwarded, ','); i >= 0 {
		forwarded = forwarded[:i]
	}
	return strings.EqualFold(strings.TrimSpace(forwarded), "https")
}

func intQuery(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// --- urlpath (backend) ---

const urlPathTTL = 5.0

// urlpath returns the current URL prefix, cached for 5s. Empty means root.
// URLPath returns the current (non-empty) URL prefix the panel is served under.
func (h *Handler) URLPath() string { return h.urlpath() }

func (h *Handler) urlpath() string {
	now := float64(time.Now().UnixNano()) / 1e9
	h.urlMu.Lock()
	defer h.urlMu.Unlock()
	if h.urlAt != 0 && now-h.urlAt < urlPathTTL {
		return h.urlValue
	}
	value := "dashboard"
	if s := h.settings(); s != nil {
		if v := strings.Trim(s.strOr("urlpath"), "/"); v != "" {
			value = v
		}
	}
	h.urlValue = value
	h.urlAt = now
	return value
}

// setURLPath persists a new prefix. Reserved prefixes are refused here too, so
// no caller can shadow a live panel route.
func (h *Handler) setURLPath(value string) (string, error) {
	value = strings.Trim(value, "/")
	if value == "" {
		value = "dashboard"
	}
	if reservedPrefixes()[strings.ToLower(value)] {
		return "", errReservedPrefix{value}
	}
	if err := setColumns(h.Svc.DB(), map[string]any{"urlpath": value}); err != nil {
		return "", errURLPathPersist{}
	}
	h.urlMu.Lock()
	h.urlValue = value
	h.urlAt = float64(time.Now().UnixNano()) / 1e9
	h.urlMu.Unlock()
	return value, nil
}

type errReservedPrefix struct{ value string }

func (e errReservedPrefix) Error() string {
	return "'" + e.value + "' is reserved and cannot be used as the panel URL path"
}

type errURLPathPersist struct{}

func (errURLPathPersist) Error() string { return "URLPATH could not be persisted" }

// reservedPrefixes are the first path segments the panel itself owns. Derived
// from the Go route table.
func reservedPrefixes() map[string]bool {
	// "doc" and "openapi.json" are served at the site root (spaHandler), not
	// under the panel prefix, so they are not strictly shadowable. They stay
	// here as belt-and-braces: a panel URL path of "doc" would otherwise
	// collide with the root-level route that the embedded SPA also reads.
	reserved := map[string]bool{
		"api": true, "assets": true, "health": true, "static": true,
		"doc": true, "openapi.json": true,
	}
	reserved[strings.ToLower(subscriptionPath())] = true
	for _, seg := range []string{
		"login", "logout", "refresh", "owner-claim", "users", "server", "nodes",
		"security", "maintenance", "tls", "https", "updater", "activity",
		"metrics", "notifications", "live", "fonts", "icons", "manifest.webmanifest", "sw.js",
	} {
		reserved[seg] = true
	}
	return reserved
}
