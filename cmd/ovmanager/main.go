// Command ovmanager is the OVManager panel binary (CLI subcommands land in
// Phase 5; for now it serves the HTTP API).
package main

import (
	"log"
	"net"
	"net/http"
	"os"

	"ovmanager-go/internal/health"
	"ovmanager-go/internal/version"
)

func main() {
	addr := net.JoinHostPort(env("HOST", "0.0.0.0"), env("PORT", "2095"))
	// ponytail: no TLS/graceful shutdown yet — install.sh terminates TLS in
	// front of the panel; add timeouts when the binary becomes the edge.
	log.Printf("ovmanager-go %s listening on %s", version.Version, addr)
	if err := http.ListenAndServe(addr, health.Router()); err != nil {
		log.Fatalf("listen %s: %v", addr, err)
	}
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
