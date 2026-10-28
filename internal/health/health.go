// Package health serves the panel /health endpoint.
//
// Contract (backend): {"status":"ok"} plus "version" for loopback
// clients, so the public internet cannot fingerprint the build.
package health

import (
	"encoding/json"
	"net"
	"net/http"

	"github.com/anonysec/OVManager/go/internal/version"
)

// Router returns the health endpoint as an http.Handler.
func Router() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", handle)
	return mux
}

func handle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"detail": "Method Not Allowed"})
		return
	}
	data := map[string]string{"status": "ok"}
	if isLoopback(r.RemoteAddr) {
		data["version"] = version.Version
	}
	writeJSON(w, http.StatusOK, data)
}

// isLoopback mirrors app.py's client_ip check: 127.0.0.1 / ::1 only.
// ponytail: X-Forwarded-For (backend.client_ip) not honoured yet — add when the
// panel sits behind the panel's own reverse proxy.
func isLoopback(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
