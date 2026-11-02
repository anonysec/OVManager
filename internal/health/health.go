// Package health serves the panel /health endpoint.
//
// Contract (backend): {"status":"ok"} plus "version" for loopback
// clients, so the public internet cannot fingerprint the build.
package health

import (
	"encoding/json"
	"net"
	"net/http"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/version"
)

// Router returns the health endpoint as an http.Handler.
func Router(trustedProxy bool) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) { handle(w, r, trustedProxy) })
	return mux
}

func handle(w http.ResponseWriter, r *http.Request, trustedProxy bool) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "Method Not Allowed"})
		return
	}
	data := map[string]string{"status": "ok"}
	if isLoopbackClient(trustedProxy, r) {
		data["version"] = version.Version
	}
	writeJSON(w, http.StatusOK, data)
}

func isLoopbackClient(trustedProxy bool, r *http.Request) bool {
	host := auth.ClientIP(trustedProxy, r)
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
