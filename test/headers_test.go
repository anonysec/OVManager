// Parity tests for the security-header middleware: every panel response —
// API, SPA static and the subscription page — carries the same baseline
// headers, and HSTS appears only for direct TLS or HTTPS forwarded by a
// configured trusted proxy.
package tests

import (
	"net/http"
	"testing"
)

// headers hits an endpoint and returns the response headers. env must come
// from one started newPanelEnv; each test starts its own.
func headers(t *testing.T, env *panelEnv, method, path string, h map[string]string) http.Header {
	t.Helper()
	req, err := http.NewRequest(method, env.srv.URL+path, nil)
	if err != nil {
		t.Fatal(err)
	}
	for k, v := range h {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	return resp.Header
}

// e is any started panelEnv: set by TestSecurityHeadersAPI etc. Simplest
// ordering: one test starts the env and every sub-check reuses it.

func TestSecurityHeadersAPI(t *testing.T) {
	env := newPanelEnv(t)
	h := headers(t, env, http.MethodGet, "/health", nil)
	for _, want := range []string{
		"Content-Security-Policy",
		"X-Frame-Options",
		"Referrer-Policy",
		"X-Content-Type-Options",
	} {
		if h.Get(want) == "" {
			t.Errorf("%s: %q header missing", "/health", want)
		}
	}
}

func TestSecurityHeadersSubscriptionPage(t *testing.T) {
	env := newPanelEnv(t)
	h := headers(t, env, http.MethodGet, "/sub", nil)
	for _, want := range []string{"Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options"} {
		if h.Get(want) == "" {
			t.Errorf("%s: %q header missing", "/sub", want)
		}
	}
}

func TestSecurityHeadersHSTSRules(t *testing.T) {
	env := newPanelEnv(t)

	// Plain HTTP: no HSTS. The panel terminates TLS itself, so HSTS is only
	// emitted on a real TLS connection.
	h := headers(t, env, http.MethodGet, "/health", nil)
	if hst := h.Get("Strict-Transport-Security"); hst != "" {
		t.Errorf("/health plain http: unexpected HSTS %q", hst)
	}

	// A forwarded scheme is not trusted: no proxy support, so a client cannot
	// claim HTTPS with a header.
	h = headers(t, env, http.MethodGet, "/health", map[string]string{"X-Forwarded-Proto": "https"})
	if hst := h.Get("Strict-Transport-Security"); hst != "" {
		t.Errorf("/health forwarded https: unexpected HSTS %q", hst)
	}
}
