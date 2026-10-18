// Command ovmanager is the OVManager panel binary and operator CLI (Phase 5).
// Run bare (or via systemd) it serves the panel; with a subcommand it acts as
// the `ovm` operator CLI.
package main

import (
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/cli"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/health"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/panel"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	"github.com/anonysec/OVManager/go/internal/users"
	"github.com/anonysec/OVManager/go/internal/version"
	"github.com/anonysec/OVManager/go/internal/webfs"
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
	if _, err := db.Migrate(conn); err != nil {
		log.Fatalf("migrate database: %v", err)
	}

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
	h.MountLogs(api)

	root := http.NewServeMux()
	root.Handle("/health", health.Router())
	root.Handle("/api/", http.StripPrefix("/api", api))
	h.MountSub(root)
	root.Handle("/", spaHandler())
	return panel.SecurityHeaders(root)
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
//
// The SPA comes from <appDir>/web/dist when that tree exists (a dev checkout,
// or an explicit OVM_APP_DIR); otherwise — a release install ships only the
// binary — it is served from the copy embedded via internal/webfs.
func spaHandler() http.Handler {
	var fsys fs.FS = webfs.Dist()
	if dist := filepath.Join(appDir(), "web", "dist"); diskIndex(dist) {
		fsys = os.DirFS(dist)
	}
	fileServer := http.FileServer(http.FS(fsys))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := strings.TrimPrefix(r.URL.Path, "/")
		if path == "doc" || path == "openapi.json" {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
			return
		}
		if path == "" {
			path = "index.html"
		}
		if _, err := fs.Stat(fsys, filepath.ToSlash(path)); err == nil {
			fileServer.ServeHTTP(w, r)
			return
		}
		index, err := fs.ReadFile(fsys, "index.html")
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write(index)
	})
}

// diskIndex reports whether dir holds a built index.html.
func diskIndex(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, "index.html"))
	return err == nil
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
