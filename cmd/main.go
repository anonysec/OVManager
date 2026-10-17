// Command ovmanager is the OVManager panel binary and operator CLI (Phase 5).
// Run bare (or via systemd) it serves the panel; with a subcommand it acts as
// the `ovm` operator CLI.
package main

import (
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"ovmanager-go/internal/auth"
	"ovmanager-go/internal/cli"
	"ovmanager-go/internal/db"
	"ovmanager-go/internal/health"
	"ovmanager-go/internal/node"
	"ovmanager-go/internal/panel"
	"ovmanager-go/internal/telemetry"
	"ovmanager-go/internal/users"
	"ovmanager-go/internal/version"
)

func main() {
	if len(os.Args) > 1 {
		os.Exit(cli.Run(os.Args[1:], os.Stdout))
	}
	dataDir := env("DATA_DIR", node.DataDir)
	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		log.Fatalf("open database: %v", err)
	}
	defer conn.Close()

	addr := net.JoinHostPort(env("HOST", "0.0.0.0"), env("PORT", "2095"))
	// ponytail: no TLS/graceful shutdown yet — install.sh terminates TLS in
	// front of the panel; add timeouts when the binary becomes the edge.
	log.Printf("ovmanager-go %s listening on %s", version.Version, addr)
	if err := http.ListenAndServe(addr, panelRouter(auth.NewService(conn, dataDir))); err != nil {
		log.Fatalf("listen %s: %v", addr, err)
	}
}

// panelRouter assembles app.py's surface: root /health, every router under
// /api, the unprefixed subscription page, and the built SPA as the fallback.
func panelRouter(svc *auth.Service) http.Handler {
	h := panel.NewHandler(svc)

	api := http.NewServeMux()
	svc.Mount(api)
	users.NewHandler(svc).Mount(api)
	node.NewHandler(svc).Mount(api)
	telemetry.NewHandler(svc).Mount(api)
	h.Mount(api)

	root := http.NewServeMux()
	root.Handle("/health", health.Router())
	root.Handle("/api/", http.StripPrefix("/api", api))
	h.MountSub(root)
	root.Handle("/", spaHandler(filepath.Join(appDir(), "web", "dist")))
	return root
}

// appDir is where .env and web/ live (backend/config.py app_dir).
func appDir() string {
	if d := os.Getenv("OVM_APP_DIR"); d != "" {
		return d
	}
	if wd, err := os.Getwd(); err == nil {
		return wd
	}
	return "."
}

// spaHandler serves the built web and falls back to index.html for the
// client-side router. Reserved prefixes answer 404 like app.py's catch-all,
// never SPA HTML.
func spaHandler(dist string) http.Handler {
	fs := http.FileServer(http.Dir(dist))
	index := filepath.Join(dist, "index.html")
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/")
		if path == "doc" || path == "openapi.json" || strings.HasPrefix(path, "assets/") {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
			return
		}
		if _, err := os.Stat(filepath.Join(dist, filepath.FromSlash(path))); err == nil {
			fs.ServeHTTP(w, r)
			return
		}
		http.ServeFile(w, r, index)
	})
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
