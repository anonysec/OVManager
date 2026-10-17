// Test scaffolding shared by the auth and users parity tests.
package goparity

import (
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"testing"

	"ovmanager-go/internal/auth"
	"ovmanager-go/internal/db"
	"ovmanager-go/internal/users"
)

// pythonBcryptHash is a real bcrypt hash minted by the Python backend's
// backend/auth/hash.py (bcrypt 12 rounds, $2b$). knownPassword must verify
// against it from Go — this is the cross-implementation hash guard.
const (
	knownPassword    = "correct-horse-battery"
	pythonBcryptHash = "$2b$12$8SlU4k4IX4m.tP5fJQuWdenXCdwIlWYz8gF4lpOuVorq83CxScpTm"
)

// testSchema mirrors the columns the ported code touches (backend/db/models.py).
const testSchema = `
CREATE TABLE admins (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
  is_owner BOOLEAN DEFAULT 0, telegram_id INTEGER);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, token_hash VARCHAR UNIQUE, username VARCHAR,
  role VARCHAR, created_at FLOAT, expires_at FLOAT, last_seen_at FLOAT,
  user_agent VARCHAR, ip VARCHAR);
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR UNIQUE, name VARCHAR UNIQUE,
  total BIGINT, used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1 NOT NULL, expiry_date DATE, is_active BOOLEAN DEFAULT 1,
  last_online DATETIME, tag VARCHAR);
CREATE TABLE settings (id INTEGER PRIMARY KEY, default_days INTEGER DEFAULT 30,
  default_traffic_gb INTEGER DEFAULT 100, default_max_users INTEGER DEFAULT 1);
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  status BOOLEAN DEFAULT 1, key VARCHAR);
CREATE TABLE user_traffic_daily (id INTEGER PRIMARY KEY, user_id INTEGER, day DATE, bytes BIGINT);
`

// newTestDB opens a throwaway SQLite file with the schema the ported code uses.
func newTestDB(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(testSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn, dir
}

// seedOwner inserts the single owner credential row (backend/auth/auth.py).
func seedOwner(t *testing.T, conn *sql.DB, username, hash string) {
	t.Helper()
	if _, err := conn.Exec(
		`INSERT INTO admins (username, password, is_owner) VALUES (?, ?, 1)`, username, hash,
	); err != nil {
		t.Fatalf("seed owner: %v", err)
	}
}

// newServer mounts the Go auth + users routers under /api, mirroring app.py's
// `api.include_router(prefix="/api", ...)`.
func newServer(t *testing.T, conn *sql.DB, dataDir string) *httptest.Server {
	t.Helper()
	svc := auth.NewService(conn, dataDir)
	inner := http.NewServeMux()
	svc.Mount(inner)
	users.NewHandler(svc).Mount(inner)
	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	srv := httptest.NewServer(root)
	t.Cleanup(srv.Close)
	return srv
}

// newHTTPServer wraps an already-built handler in a live test server.
func newHTTPServer(t *testing.T, handler http.Handler) string {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return srv.URL
}

// postForm posts OAuth2 password-form credentials like FastAPI's
// OAuth2PasswordRequestForm expects.
func postForm(t *testing.T, base, path string, form url.Values) *http.Response {
	t.Helper()
	res, err := http.Post(base+path, "application/x-www-form-urlencoded", strings.NewReader(form.Encode()))
	if err != nil {
		t.Fatalf("POST %s: %v", path, err)
	}
	return res
}

// doJSON performs a JSON request and returns the response plus decoded body.
func doJSON(t *testing.T, method, url, token string, body any) (*http.Response, map[string]any) {
	t.Helper()
	var reader io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		reader = strings.NewReader(string(raw))
	}
	req, err := http.NewRequest(method, url, reader)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
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
	var decoded map[string]any
	_ = json.Unmarshal(raw, &decoded)
	return res, decoded
}

// login runs a successful login and returns the bearer token.
func login(t *testing.T, base, username, password string) map[string]any {
	t.Helper()
	res := postForm(t, base, "/api/login", url.Values{"username": {username}, "password": {password}})
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("login status = %d, want 200", res.StatusCode)
	}
	var got map[string]any
	if err := json.NewDecoder(res.Body).Decode(&got); err != nil {
		t.Fatalf("decode login: %v", err)
	}
	return got
}
