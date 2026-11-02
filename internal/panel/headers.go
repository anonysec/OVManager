// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Security-header middleware (all panel responses: API, SPA, subscription
// page). HSTS is emitted for a direct TLS connection or an HTTPS request
// forwarded by a proxy explicitly configured as trusted.
package panel

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
)

type contextKey string

const NonceContextKey contextKey = "csp-nonce"

// NonceFromContext retrieves the per-request CSP nonce from context.
func NonceFromContext(ctx context.Context) string {
	if ctx == nil {
		return ""
	}
	if n, ok := ctx.Value(NonceContextKey).(string); ok {
		return n
	}
	return ""
}

func generateNonce() string {
	b := make([]byte, 16)
	if _, err := io.ReadFull(rand.Reader, b); err != nil {
		return "static-csp-nonce"
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		nonce := generateNonce()
		ctx := context.WithValue(r.Context(), NonceContextKey, nonce)
		r = r.WithContext(ctx)

		h := w.Header()
		csp := fmt.Sprintf(
			"default-src 'self'; script-src 'self' 'nonce-%s'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
			nonce,
		)
		h.Set("Content-Security-Policy", csp)
		h.Set("X-Frame-Options", "DENY")
		h.Set("Referrer-Policy", "strict-origin-when-cross-origin")
		h.Set("X-Content-Type-Options", "nosniff")
		if externallySecure(r) {
			h.Set("Strict-Transport-Security", "max-age=31536000")
		}
		next.ServeHTTP(w, r)
	})
}

// SecurityHeaders wraps an assembled root handler. Exported because the
// wiring lives in cmd (panelRouter) and the tests mirror it.
func SecurityHeaders(next http.Handler) http.Handler {
	return securityHeaders(next)
}
