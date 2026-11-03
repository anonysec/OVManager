package main

import (
	"bytes"
	"net/http"
	"testing"
	"time"
)

func TestServeMode(t *testing.T) {
	t.Setenv("HOST", "")
	cases := []struct {
		tls  bool
		port string
		addr string
		use  bool
	}{
		{false, "2095", "127.0.0.1:2095", false},
		{true, "2095", "0.0.0.0:2095", true},
		{false, "8080", "127.0.0.1:8080", false},
		{true, "8080", "0.0.0.0:8080", true},
	}
	for _, c := range cases {
		addr, use := serveMode(c.tls, c.port)
		if addr != c.addr || use != c.use {
			t.Errorf("serveMode(%v,%s) = (%s,%v), want (%s,%v)", c.tls, c.port, addr, use, c.addr, c.use)
		}
	}
	// invariant: no plaintext on 0.0.0.0 by default
	if a, _ := serveMode(false, "2095"); a == "0.0.0.0:2095" {
		t.Fatal("plaintext bound to 0.0.0.0")
	}
}

// The container image sets HOST=0.0.0.0: a published port forwards to the
// container's own address, so a loopback bind inside the container is
// unreachable from outside.
func TestServeModeHonoursHost(t *testing.T) {
	t.Setenv("HOST", "0.0.0.0")
	if a, _ := serveMode(false, "2095"); a != "0.0.0.0:2095" {
		t.Errorf("plaintext with HOST=0.0.0.0 = %s, want 0.0.0.0:2095", a)
	}
	// TLS always binds every interface, whatever HOST says.
	if a, _ := serveMode(true, "2095"); a != "0.0.0.0:2095" {
		t.Errorf("TLS bind = %s, want 0.0.0.0:2095", a)
	}
}

func TestNewServerTimeouts(t *testing.T) {
	srv := newServer("127.0.0.1:2095", http.NewServeMux())
	if srv.ReadHeaderTimeout != 10*time.Second {
		t.Errorf("ReadHeaderTimeout = %v", srv.ReadHeaderTimeout)
	}
	if srv.ReadTimeout != 10*time.Minute {
		t.Errorf("ReadTimeout = %v", srv.ReadTimeout)
	}
	if srv.IdleTimeout != 120*time.Second {
		t.Errorf("IdleTimeout = %v", srv.IdleTimeout)
	}
	if srv.WriteTimeout != 0 {
		t.Errorf("WriteTimeout = %v, want 0", srv.WriteTimeout)
	}
}

func TestDecoyHandlerNoUnnoncedScripts(t *testing.T) {
	h := decoyHandler()
	w := &responseRecorder{header: http.Header{}}
	req := &http.Request{Method: http.MethodGet, URL: nil}
	// build a minimal request
	r, _ := http.NewRequest(http.MethodGet, "/", nil)
	h.ServeHTTP(w, r)
	if w.code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", w.code)
	}
	body := w.body.String()
	if containsUnnoncedScript(body) {
		t.Fatalf("decoy page contains an inline script without a nonce")
	}
	if containsSubstring(body, "static-csp-nonce") {
		t.Fatalf("decoy page leaks static-csp-nonce")
	}
	_ = req
}

// responseRecorder is a minimal http.ResponseWriter for tests.
type responseRecorder struct {
	header http.Header
	code   int
	body   bytes.Buffer
}

func (r *responseRecorder) Header() http.Header { return r.header }
func (r *responseRecorder) Write(b []byte) (int, error) {
	if r.code == 0 {
		r.code = http.StatusOK
	}
	return r.body.Write(b)
}
func (r *responseRecorder) WriteHeader(code int) { r.code = code }

func containsUnnoncedScript(s string) bool {
	i := 0
	for {
		idx := indexOf(s, "<script", i)
		if idx < 0 {
			return false
		}
		// find end of tag
		end := indexOf(s, ">", idx)
		if end < 0 {
			return true
		}
		tag := s[idx:end]
		if !containsSubstring(tag, "nonce=") {
			return true
		}
		i = end + 1
	}
}

func containsSubstring(s, sub string) bool {
	return indexOf(s, sub, 0) >= 0
}

func indexOf(s, sub string, start int) int {
	if start > len(s) {
		start = len(s)
	}
	for i := start; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
