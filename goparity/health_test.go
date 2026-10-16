// Package goparity holds cross-implementation parity tests: the Go server must
// answer byte-compatible with the Python backend it replaces.
package goparity

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"testing"

	"ovmanager-go/internal/db"
	"ovmanager-go/internal/health"
)

// pythonVersion reads backend/version.py so the Go constant cannot drift while
// the Python backend still ships.
func pythonVersion(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "backend", "version.py"))
	if err != nil {
		t.Fatalf("read backend/version.py: %v", err)
	}
	m := regexp.MustCompile(`__version__\s*=\s*"([^"]+)"`).FindSubmatch(raw)
	if m == nil {
		t.Fatalf("no __version__ in backend/version.py")
	}
	return string(m[1])
}

// TestHealthMatchesPython mirrors backend/app.py /health: {"status":"ok"} plus
// "version" for loopback clients (httptest is loopback, as is the panel itself).
func TestHealthMatchesPython(t *testing.T) {
	srv := httptest.NewServer(health.Router())
	defer srv.Close()

	res, err := http.Get(srv.URL + "/health")
	if err != nil {
		t.Fatalf("GET /health: %v", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}
	if ct := res.Header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("content-type = %q, want application/json", ct)
	}
	var got map[string]any
	if err := json.NewDecoder(res.Body).Decode(&got); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if got["status"] != "ok" {
		t.Errorf("status field = %v, want ok", got["status"])
	}
	want := pythonVersion(t)
	if got["version"] != want {
		t.Errorf("version = %v, want %q (backend/version.py)", got["version"], want)
	}
	if len(got) != 2 {
		t.Errorf("keys = %v, want exactly status+version", got)
	}
}

// TestOpenAppliesPragmas guards the DSN pragmas: modernc silently ignores a
// malformed _pragma=, so assert the ones the Python engine sets.
func TestOpenAppliesPragmas(t *testing.T) {
	path := filepath.Join(t.TempDir(), "test.db")
	conn, err := db.Open(path)
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	defer conn.Close()

	for pragma, want := range map[string]string{
		"journal_mode": "wal",
		"synchronous":  "1",
		"busy_timeout": "30000",
		"foreign_keys": "1",
		"mmap_size":    "268435456",
		"cache_size":   "-32768",
		"temp_store":   "2",
	} {
		var got string
		if err := conn.QueryRow("PRAGMA " + pragma).Scan(&got); err != nil {
			t.Fatalf("PRAGMA %s: %v", pragma, err)
		}
		if got != want {
			t.Errorf("PRAGMA %s = %q, want %q", pragma, got, want)
		}
	}
}

// TestHealthNonGet mirrors app.py's 405 shape for non-GET on /health.
func TestHealthNonGet(t *testing.T) {
	srv := httptest.NewServer(health.Router())
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/health", nil)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("POST /health: %v", err)
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405", res.StatusCode)
	}
	var got map[string]any
	if err := json.NewDecoder(res.Body).Decode(&got); err != nil {
		t.Fatalf("decode body: %v", err)
	}
	if got["detail"] != "Method Not Allowed" {
		t.Errorf("detail = %v, want Method Not Allowed", got["detail"])
	}
}
