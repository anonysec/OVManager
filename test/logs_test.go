// Parity tests for the panel journal-log viewer (plan Task 2):
// unit whitelist against the nodes table, charset sanitize, lines cap,
// journalctl permission short-circuit and the RequireUser gate.
//
// journalctl is stubbed on PATH (panel_test.go's empty-PATH trick would leave
// this endpoint without the one binary it runs). One successful login per
// helper call — the login rate limits are real (they bucket failures, but the
// helpers still follow the single-login pattern of newPanelEnv).
package tests

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/panel"
)

const journalStubEcho = `#!/bin/sh
echo "ARGS: $*"
echo "journal line one"
echo "journal line two"
`

const journalStubNoPermission = `#!/bin/sh
echo "No journal files were opened due to insufficient permissions." >&2
exit 1
`

// logsEnv duplicates newPanelEnv with a journalctl stub on PATH and the
// GET /logs route mounted.
type logsEnv struct {
	srv    *httptest.Server
	token  string
	sqlite *sql.DB
	svc    *auth.Service
}

func logsEnvFor(t *testing.T, stub string) logsEnv {
	t.Helper()
	dataDir := t.TempDir()
	stubDir := t.TempDir()
	t.Setenv("DATA_DIR", dataDir)
	t.Setenv("PATH", stubDir)
	t.Setenv("HOME", stubDir)
	t.Setenv("OVM_APP_DIR", t.TempDir())

	if err := os.WriteFile(filepath.Join(stubDir, "journalctl"), []byte(stub), 0o755); err != nil {
		t.Fatalf("write journalctl stub: %v", err)
	}

	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(panelSchema); err != nil {
		t.Fatalf("panel schema: %v", err)
	}
	seedOwner(t, conn, "owner", pythonBcryptHash)

	svc := auth.NewService(conn, dataDir)
	h := panel.NewHandler(svc)
	inner := http.NewServeMux()
	svc.Mount(inner)
	h.MountLogs(inner)

	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	srv := httptest.NewServer(root)
	t.Cleanup(srv.Close)

	token, _ := login(t, srv.URL, "owner", knownPassword)["access_token"].(string)
	if token == "" {
		t.Fatal("login returned no access_token")
	}
	return logsEnv{srv: srv, token: token, sqlite: conn, svc: svc}
}

func TestLogsUnitWhitelist(t *testing.T) {
	env := logsEnvFor(t, journalStubEcho)
	// Unknown unit.
	res, raw := rawReq(t, "GET", env.srv.URL+"/api/logs?unit=openvpn-nope&lines=10", env.token, nil, "")
	body := string(raw)

	if res.StatusCode != http.StatusBadRequest {
		t.Fatalf("unknown unit status = %d, want 400 (%s)", res.StatusCode, body)
	}
	if !strings.Contains(body, "Unknown unit") {
		t.Fatalf("unknown unit body %q lacks the Unknown-unit detail", body)
	}

	// Charset sanitize, traversal and case traps land on the same 400.
	for _, bad := range []string{"openvpn-x:kill", "openvpn-Europe", "../etc", "ovmanager $(id)"} {
		res, raw := rawReq(t, "GET", env.srv.URL+"/api/logs?unit="+bad+"&lines=10", env.token, nil, "")
		if res.StatusCode != http.StatusBadRequest {
			t.Fatalf("unit %q status = %d, want 400 (body %q)", bad, res.StatusCode, raw)
		}
	}

	// A node row opens its openvpn-<name> unit.
	if _, err := env.sqlite.Exec(
		`INSERT INTO nodes (name, address, status, key) VALUES ('eu-1', '203.0.113.10', 1, 'k')`,
	); err != nil {
		t.Fatalf("seed node: %v", err)
	}
	res, raw = rawReq(t, "GET", env.srv.URL+"/api/logs?unit=openvpn-eu-1&lines=10", env.token, nil, "")
	body = string(raw)
	if res.StatusCode != http.StatusOK {
		t.Fatalf("node unit status = %d, want 200 (%s)", res.StatusCode, body)
	}
	if ct := res.Header.Get("Content-Type"); ct != "text/plain; charset=utf-8" {
		t.Fatalf("content type = %q", ct)
	}
	for _, want := range []string{"-u openvpn-eu-1", "-o cat", "--no-pager", "journal line one"} {
		if !strings.Contains(body, want) {
			t.Fatalf("journal invocation/body %q lacks %q", body, want)
		}
	}
	if strings.Contains(body, "-f") {
		t.Fatalf("journal read must not follow (%q)", body)
	}
}

func TestLogsLinesCap(t *testing.T) {
	env := logsEnvFor(t, journalStubEcho)
	for _, c := range []struct {
		query string
		want  string
	}{
		{"/api/logs", "-n 200"},           // default
		{"/api/logs?lines=abc", "-n 200"}, // unparseable → default
		{"/api/logs?lines=900", "-n 500"}, // capped
		{"/api/logs?lines=3", "-n 3"},
		{"/api/logs?lines=0", "-n 1"},  // clamp low
		{"/api/logs?lines=-7", "-n 1"}, // clamp low
	} {
		res, raw := rawReq(t, "GET", env.srv.URL+c.query, env.token, nil, "")
		if res.StatusCode != http.StatusOK || !strings.Contains(string(raw), c.want) {
			t.Fatalf("GET /api/logs?%s → %d %q, want %s", c.query, res.StatusCode, raw, c.want)
		}
	}
}

func TestLogsUnreadable(t *testing.T) {
	env := logsEnvFor(t, journalStubNoPermission)
	res, raw := rawReq(t, "GET", env.srv.URL+"/api/logs?lines=10", env.token, nil, "")
	if res.StatusCode != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502 (%s)", res.StatusCode, raw)
	}
	if !strings.Contains(string(raw), "journalctl unreadable (add the panel user to systemd-journal)") {
		t.Fatalf("body %q lacks the permission detail", raw)
	}
}

func TestLogsGate(t *testing.T) {
	env := logsEnvFor(t, journalStubEcho)

	// Anonymous → 401 from RequireUser.
	res, _ := rawReq(t, "GET", env.srv.URL+"/api/logs?lines=10", "", nil, "")
	if res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("anonymous status = %d, want 401", res.StatusCode)
	}

	// Any logged-in admin, not just the owner: a role="admin" session rides
	// the same RequireUser gate. Login only mints owner sessions, so the
	// admin session is issued directly (IssueSession) against a seeded
	// is_owner=0 row.
	if _, err := env.sqlite.Exec(
		`INSERT INTO admins (username, password, is_owner) VALUES ('second', ?, 0)`, pythonBcryptHash,
	); err != nil {
		t.Fatalf("seed admin: %v", err)
	}
	rec := httptest.NewRecorder()
	env.svc.IssueSession(rec, httptest.NewRequest("POST", "/api/login", nil), "second", "admin")
	var issued map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &issued); err != nil {
		t.Fatalf("decode issued session: %v", err)
	}
	token, _ := issued["access_token"].(string)
	if token == "" {
		t.Fatal("IssueSession returned no access_token")
	}
	res, raw := rawReq(t, "GET", env.srv.URL+"/api/logs?lines=10", token, nil, "")
	if res.StatusCode != http.StatusOK {
		t.Fatalf("admin status = %d, want 200 (%s)", res.StatusCode, raw)
	}
}
