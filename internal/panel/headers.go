// Security-header middleware (all panel responses: API, SPA, subscription
// page). HSTS is emitted only when the connection itself is TLS — the panel
// is served plain HTTP behind a front proxy in release installs — either via
// r.TLS or an X-Forwarded-Proto: https from that proxy.
package panel

import "net/http"

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("Content-Security-Policy",
			"default-src 'self'; font-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'")
		h.Set("X-Frame-Options", "DENY")
		h.Set("Referrer-Policy", "strict-origin-when-cross-origin")
		h.Set("X-Content-Type-Options", "nosniff")
		if r.TLS != nil || r.Header.Get("X-Forwarded-Proto") == "https" {
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
