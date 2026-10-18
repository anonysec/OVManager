// Package panel ports the remaining Python routers (Phase 4): health overview,
// panel settings, security summary, TLS management, updater, maintenance and
// the subscription page.
//
// Configuration mirrors backend/config.py: process environment first, the
// panel's .env second (pydantic-settings precedence). The .env is read from
// OVM_APP_DIR — install.sh chdirs to APP_DIR before exec — falling back to the
// working directory.
package panel

import (
	"database/sql"
	"encoding/json"
	"net"
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

	// urlpath cache (backend/urlpath/_core.py, 5s TTL). Per-handler rather
	// than process-global: observable behaviour is identical for the single
	// panel process, and it keeps tests hermetic.
	urlMu    sync.Mutex
	urlValue string
	urlAt    float64

	// certificate writes are serialized like _CERTIFICATE_LOCK.
	certMu sync.Mutex

	// issuance (bundle: the whole ACME flow owns the certificate state for
	// its duration) is serialized separately from the short file writes.
	acmeMu sync.Mutex
}

// NewHandler builds the router over the shared auth service.
func NewHandler(svc *auth.Service) *Handler {
	return &Handler{Svc: svc, startedAt: time.Now()}
}

// Mount registers the Phase 4 routes relative to the caller's prefix (app.py
// includes every router under /api).
func (h *Handler) Mount(mux *http.ServeMux) {
	owner := h.Svc.RequireOwner
	user := h.Svc.RequireUser

	mux.HandleFunc("GET /health/overview", owner(h.healthOverview))
	mux.HandleFunc("GET /health/login-health", owner(h.loginHealth))
	mux.HandleFunc("GET /health/login-diagnostics/{username}", owner(h.loginDiagnostics))
	mux.HandleFunc("GET /health/setup", user(h.healthSetup))
	mux.HandleFunc("GET /health/tls", user(h.healthTLS))

	mux.HandleFunc("GET /server/settings", owner(h.getSettings))
	mux.HandleFunc("GET /server/settings/", owner(h.getSettings))
	mux.HandleFunc("PUT /server/settings/timezone", owner(h.updateTimezone))
	mux.HandleFunc("PUT /server/settings/subscription", owner(h.updateSubscription))
	mux.HandleFunc("PUT /server/settings/domain", owner(h.updateDomain))
	mux.HandleFunc("PUT /server/settings/bot", owner(h.updateBotConfig))
	mux.HandleFunc("PUT /server/settings/urlpath", owner(h.updateURLPath))
	mux.HandleFunc("POST /server/alerts/test", owner(h.testAlert))
	mux.HandleFunc("GET /server/info", owner(h.serverInfo))

	mux.HandleFunc("GET /security/summary", owner(h.securitySummary))

	mux.HandleFunc("GET /maintenance/backup/list", owner(h.backupList))
	mux.HandleFunc("GET /maintenance/backup/download", owner(h.backupDownload))
	mux.HandleFunc("POST /maintenance/backup", owner(h.backupCreate))
	mux.HandleFunc("POST /maintenance/backup/restore", owner(h.backupRestore))
	mux.HandleFunc("POST /maintenance/sync-limits", owner(h.syncLimits))
	mux.HandleFunc("POST /maintenance/clean-stale", owner(h.cleanStale))
	mux.HandleFunc("POST /maintenance/restart", owner(h.restartPanel))
	mux.HandleFunc("POST /maintenance/cleanup/preview", owner(h.cleanupPreview))
	mux.HandleFunc("POST /maintenance/cleanup/run", owner(h.cleanupRun))
	mux.HandleFunc("POST /maintenance/usage/reset-all", owner(h.usageResetAll))
	mux.HandleFunc("POST /maintenance/usage/purge", owner(h.usagePurge))

	mux.HandleFunc("GET /tls/settings", owner(h.tlsGetSettings))
	mux.HandleFunc("PUT /tls/settings", owner(h.tlsPutSettings))
	mux.HandleFunc("GET /tls/status", owner(h.tlsStatus))
	mux.HandleFunc("POST /tls/upload", owner(h.tlsUpload))
	mux.HandleFunc("POST /tls/self-signed", owner(h.tlsSelfSigned))
	mux.HandleFunc("POST /tls/renew", owner(h.tlsRenew))
	mux.HandleFunc("POST /tls/rollback", owner(h.tlsRollback))
	mux.HandleFunc("POST /tls/restart", owner(h.tlsRestart))

	// Built-in ACME issuance (no acme.sh dependency on the host).
	mux.HandleFunc("POST /tls/acme", owner(h.tlsACMEIssue))

	// https_router aliases (backend/routers/tls.py bottom).
	mux.HandleFunc("GET /https/status", owner(h.tlsStatus))
	mux.HandleFunc("POST /https/existing", owner(h.tlsUpload))
	mux.HandleFunc("POST /https/temporary", owner(h.tlsSelfSigned))
	mux.HandleFunc("POST /https/automatic", owner(h.tlsRenew))
	mux.HandleFunc("POST /https/rollback", owner(h.tlsRollback))
	mux.HandleFunc("POST /https/restart", owner(h.tlsRestart))

	mux.HandleFunc("GET /updater/status", owner(h.updateStatus))
	mux.HandleFunc("GET /updater/operation", owner(h.updateOperation))
	mux.HandleFunc("POST /updater/run", owner(h.runUpdate))

	// Daily ACME renewal (T-30d) + boot issuance when the installer wired
	// OVM_ACME_DOMAIN. No-op without an enrolled domain.
	h.startACMEWorker()

	// Telegram ops channel: one worker goroutine (daily summary at
	// telegram_summary_time, immediate expired/over-quota events, node/CPU
	// threshold sweeps through telemetry.CollectMetrics). No-op while the bot
	// is disabled or unconfigured.
	h.startTelegramWorker()
}

// MountSub registers the subscription page at /<SUBSCRIPTION_PATH>, outside
// the /api prefix (app.py includes that router unprefixed).
func (h *Handler) MountSub(mux *http.ServeMux) {
	prefix := "/" + subscriptionPath()
	mux.HandleFunc("GET "+prefix+"/static/subscription.js", h.subStaticJS)
	mux.HandleFunc("GET "+prefix+"/download/{uuid}/{node_name}", h.subDownload)
	mux.HandleFunc("GET "+prefix+"/{uuid}", h.subPage)
}

// --- configuration (backend/config.py + backend/tls_paths.py) ---

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

// envFileValues reads the uncommented KEY=VALUE pairs from the panel's .env.
func envFileValues() map[string]string {
	values := map[string]string{}
	raw, err := os.ReadFile(filepath.Join(appDir(), ".env"))
	if err != nil {
		return values
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		key, value, _ := strings.Cut(line, "=")
		values[strings.TrimSpace(key)] = strings.Trim(strings.TrimSpace(value), "'\"")
	}
	return values
}

// envOrFile is pydantic-settings precedence: a real environment variable wins
// over the .env line.
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
	return "/etc/ovmanager/tls/privkey.pem"
}

func sslCertPath() string {
	if v := envOrFile("SSL_CERTFILE"); v != "" {
		return v
	}
	return "/etc/ovmanager/tls/fullchain.pem"
}

func subscriptionPath() string {
	if v := strings.Trim(envOrFile("SUBSCRIPTION_PATH"), "/"); v != "" {
		return v
	}
	return "sub"
}

func serverHost() string {
	if v := envOrFile("HOST"); v != "" {
		return v
	}
	return "0.0.0.0"
}

func serverPort() int {
	if v := envOrFile("PORT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return 2095
}

// --- settings row (backend/db/crud/settings.py) ---

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

// strOr is the raw DB value ("" for NULL) — the Python `getattr(x, col, None) or ""`.
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

// numOrNull is Python's `getattr(x, col, None)` for ints.
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

// intOr is Python's `as_int(getattr(...), default)` for the alert thresholds:
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
	return readSettings(h.Svc.DB)
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
	for key, value := range values {
		if _, err := db.Exec(`UPDATE settings SET `+key+` = ? WHERE id = (SELECT MIN(id) FROM settings)`, value); err != nil {
			return err
		}
	}
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

// clientIP mirrors backend/client_ip.client_ip: X-Forwarded-For only behind a
// trusted proxy.
func (h *Handler) clientIP(r *http.Request) string {
	if h.Svc.TrustedProxy {
		if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
			parts := strings.Split(xff, ",")
			if v := strings.TrimSpace(parts[len(parts)-1]); v != "" {
				return v
			}
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	return host
}

// baseURL is FastAPI's str(request.base_url).
func baseURL(r *http.Request) string {
	scheme := "http"
	if r.TLS != nil {
		scheme = "https"
	}
	return scheme + "://" + r.Host + "/"
}

func intQuery(r *http.Request, key string, def int) int {
	if v := r.URL.Query().Get(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// --- urlpath (backend/urlpath/_core.py) ---

const urlPathTTL = 5.0

// urlpath returns the current URL prefix, cached for 5s. Empty means root.
func (h *Handler) urlpath() string {
	now := float64(time.Now().UnixNano()) / 1e9
	h.urlMu.Lock()
	defer h.urlMu.Unlock()
	if h.urlAt != 0 && now-h.urlAt < urlPathTTL {
		return h.urlValue
	}
	value := ""
	if s := h.settings(); s != nil {
		value = strings.Trim(s.strOr("urlpath"), "/")
	}
	h.urlValue = value
	h.urlAt = now
	return value
}

// setURLPath persists a new prefix. Reserved prefixes are refused here too, so
// no caller can shadow a live panel route.
func (h *Handler) setURLPath(value string) (string, error) {
	value = strings.Trim(value, "/")
	if value != "" && reservedPrefixes()[strings.ToLower(value)] {
		return "", errReservedPrefix{value}
	}
	if err := setColumns(h.Svc.DB, map[string]any{"urlpath": value}); err != nil {
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
// from the Go route table (the Python version walked api.routes).
func reservedPrefixes() map[string]bool {
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
