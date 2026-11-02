// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSecurityHeadersCSPHardening(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()

	handler := SecurityHeaders(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nonce := NonceFromContext(r.Context())
		if nonce == "" {
			t.Errorf("expected CSP nonce in request context, got empty")
		}
		w.WriteHeader(http.StatusOK)
	}))

	handler.ServeHTTP(w, req)

	csp := w.Header().Get("Content-Security-Policy")
	if csp == "" {
		t.Fatal("Content-Security-Policy header is missing")
	}

	requiredDirectives := []string{
		"base-uri 'self'",
		"object-src 'none'",
		"form-action 'self'",
		"frame-ancestors 'none'",
		"script-src 'self' 'nonce-",
	}

	for _, dir := range requiredDirectives {
		if !strings.Contains(csp, dir) {
			t.Errorf("CSP missing directive %q: full CSP = %q", dir, csp)
		}
	}

	// Verify unsafe-inline is removed from script-src
	for _, part := range strings.Split(csp, ";") {
		part = strings.TrimSpace(part)
		if strings.HasPrefix(part, "script-src") {
			if strings.Contains(part, "'unsafe-inline'") {
				t.Errorf("SECURITY FLAW: script-src contains 'unsafe-inline': %s", part)
			}
		}
	}
}
