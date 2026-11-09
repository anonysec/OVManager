// Package health serves the panel /health endpoint.
//
// Contract (backend): {"status":"ok"} plus "version" for loopback
// clients, so the public internet cannot fingerprint the build.
package health

import (
	"net"
	"net/http"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/version"
)

// Router returns the health endpoint as an http.Handler.
func Router(trustedProxy bool) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) { handle(w, r, trustedProxy) })
	return mux
}

func handle(w http.ResponseWriter, r *http.Request, trustedProxy bool) {
	if r.Method != http.MethodGet {
		auth.WriteJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "Method Not Allowed"})
		return
	}
	data := map[string]string{"status": "ok"}
	if isLoopbackClient(trustedProxy, r) {
		data["version"] = version.Version
	}
	auth.WriteJSON(w, http.StatusOK, data)
}

func isLoopbackClient(trustedProxy bool, r *http.Request) bool {
	host := auth.ClientIP(trustedProxy, r)
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
