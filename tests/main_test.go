// Cutover guard for Phase 6 Task 1: the binary, run bare (no subcommand), must
// serve the panel — not just the CLI. app.py's surface is root /health plus the
// whole API behind the auth gate; the plan's parity probe is /health + an
// authenticated /api route + the /login method/credential shapes.
package tests

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// TestBinaryServesPanel builds cmd/ovmanager, execs it bare, and asserts it
// answers the panel contract. It fails while main.go only serves /health.
func TestBinaryServesPanel(t *testing.T) {
	bin := filepath.Join(t.TempDir(), "ovmanager")
	build := exec.Command("go", "build", "-o", bin, "./cmd/ovmanager")
	build.Dir = ".."
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("go build: %v\n%s", err, out)
	}

	port := freePort(t)
	cmd := exec.Command(bin)
	cmd.Env = append(os.Environ(),
		"HOST=127.0.0.1",
		"PORT="+port,
		"DATA_DIR="+t.TempDir(),
		"OVM_APP_DIR="+t.TempDir(),
	)
	if err := cmd.Start(); err != nil {
		t.Fatalf("start binary: %v", err)
	}
	t.Cleanup(func() {
		_ = cmd.Process.Kill()
		_, _ = cmd.Process.Wait()
	})

	base := "http://127.0.0.1:" + port
	waitReady(t, base+"/health")

	// 1. Root /health answers the app contract (loopback → version field).
	res, err := http.Get(base + "/health")
	if err != nil {
		t.Fatalf("GET /health: %v", err)
	}
	var health map[string]any
	_ = json.NewDecoder(res.Body).Decode(&health)
	res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("GET /health status = %d, want 200", res.StatusCode)
	}
	if health["status"] != "ok" {
		t.Errorf("/health status field = %v, want ok", health["status"])
	}
	if _, ok := health["version"]; !ok {
		t.Errorf("/health from loopback missing version: %v", health)
	}

	// 2. The /api surface is mounted and gated: no token → 401 Bearer.
	for _, path := range []string{"/api/users/", "/api/health/overview"} {
		req, _ := http.NewRequest(http.MethodGet, base+path, nil)
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("GET %s: %v", path, err)
		}
		body, _ := io.ReadAll(res.Body)
		res.Body.Close()
		if res.StatusCode != http.StatusUnauthorized {
			t.Errorf("GET %s status = %d, want 401 (body %s)", path, res.StatusCode, body)
		}
		if res.Header.Get("WWW-Authenticate") != "Bearer" {
			t.Errorf("GET %s WWW-Authenticate = %q, want Bearer", path, res.Header.Get("WWW-Authenticate"))
		}
	}

	// 3. /login is POST-only (GET → 405) and rejects bad credentials (401).
	res, err = http.Get(base + "/api/login")
	if err != nil {
		t.Fatalf("GET /api/login: %v", err)
	}
	res.Body.Close()
	if res.StatusCode != http.StatusMethodNotAllowed {
		t.Errorf("GET /api/login status = %d, want 405", res.StatusCode)
	}
	res, err = http.Post(base+"/api/login", "application/x-www-form-urlencoded",
		nil)
	if err != nil {
		t.Fatalf("POST /api/login: %v", err)
	}
	body, _ := io.ReadAll(res.Body)
	res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Errorf("POST /api/login (no creds) status = %d, want 401 (body %s)", res.StatusCode, body)
	}
}

// freePort reserves then releases a loopback port for the child binary.
func freePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve port: %v", err)
	}
	defer l.Close()
	_, port, _ := net.SplitHostPort(l.Addr().String())
	return port
}

// waitReady polls until the child answers or the deadline passes.
func waitReady(t *testing.T, url string) {
	t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		res, err := http.Get(url)
		if err == nil {
			res.Body.Close()
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("server never became ready at %s", url)
}
