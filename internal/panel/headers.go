// Security-header middleware (all panel responses: API, SPA, subscription
// page). HSTS is emitted for a direct TLS connection or an HTTPS request
// forwarded by a proxy explicitly configured as trusted.
package panel

import "net/http"

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		h := w.Header()
		h.Set("Content-Security-Policy",
			"default-src 'self'; script-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'")
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
