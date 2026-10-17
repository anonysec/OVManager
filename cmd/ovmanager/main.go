// Command ovmanager is the OVManager panel binary and operator CLI (Phase 5).
// Run bare (or via systemd) it serves the panel; with a subcommand it acts as
// the `ovm` operator CLI.
package main

import (
	"log"
	"net"
	"net/http"
	"os"

	"ovmanager-go/internal/cli"
	"ovmanager-go/internal/health"
	"ovmanager-go/internal/version"
)

func main() {
	if len(os.Args) > 1 {
		os.Exit(cli.Run(os.Args[1:], os.Stdout))
	}
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
