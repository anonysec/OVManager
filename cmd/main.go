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

	port := env("PORT", "2095")
	migrateLegacyTLS(dataDir)
	certFile := panel.SSLCertPath()
	keyFile := panel.SSLKeyPath()
	tlsEnabled := fileExists(certFile) && fileExists(keyFile)

	handler := panelRouter(auth.NewService(conn, dataDir))

	addr, useTLS := serveMode(tlsEnabled, port)
	if useTLS {
		log.Printf("ovmanager-go %s listening on https://%s (TLS)", version.Version, addr)
		if err := http.ListenAndServeTLS(addr, certFile, keyFile, handler); err != nil {
			log.Fatalf("listen %s: %v", addr, err)
		}
	} else {
		log.Printf("ovmanager-go %s listening on http://%s (no TLS)", version.Version, addr)
		if err := http.ListenAndServe(addr, handler); err != nil {
			log.Fatalf("listen %s: %v", addr, err)
		}
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

	prefix := "/" + h.URLPath()
	root.Handle(prefix, http.RedirectHandler(prefix+"/", http.StatusMovedPermanently))
	root.Handle(prefix+"/", spaHandler())

	// Decoy at the site root so the panel is never exposed on "/".
	root.Handle("/", decoyHandler())
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

// decoyHandler serves a generic placeholder at the site root so the panel is
// never reachable from "/".
func decoyHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte("<!doctype html><html><head><title>404 Not Found</title></head><body><h1>Not Found</h1><p>The requested URL was not found on this server.</p></body></html>"))
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

// serveMode returns the bind address and whether TLS is used. The invariant:
// plaintext is never bound to 0.0.0.0; TLS binds all interfaces.
func serveMode(tlsEnabled bool, port string) (string, bool) {
	if tlsEnabled {
		return net.JoinHostPort("0.0.0.0", port), true
	}
	return net.JoinHostPort("127.0.0.1", port), false
}

func fileExists(p string) bool {
	if p == "" {
		return false
	}
	info, err := os.Stat(p)
	return err == nil && !info.IsDir()
}

// migrateLegacyTLS copies the pre-declaration pair in DATA_DIR/tls onto the
// declared paths when the declared ones are empty, so an install that keeps
// its certificate in the legacy location does not silently fall back to plain
// HTTP after the restart that lands the declared-path resolution (tls.py
// migrate_legacy_tls). Copy, never move: the legacy files stay as a fallback.
func migrateLegacyTLS(dataDirPath string) {
	certPath := panel.SSLCertPath()
	keyPath := panel.SSLKeyPath()
	if fileExists(certPath) && fileExists(keyPath) {
		return
	}
	legacyCert := filepath.Join(dataDirPath, "tls", "fullchain.pem")
	legacyKey := filepath.Join(dataDirPath, "tls", "privkey.pem")
	if !fileExists(legacyCert) || !fileExists(legacyKey) {
		return
	}
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil {
		log.Printf("legacy tls migration: %v", err)
		return
	}
	if err := copyDiskFile(legacyCert, certPath, 0o644); err != nil {
		log.Printf("legacy tls migration: %v", err)
		return
	}
	if err := copyDiskFile(legacyKey, keyPath, 0o600); err != nil {
		log.Printf("legacy tls migration: %v", err)
		return
	}
	log.Printf("legacy tls migration: copied %s and %s onto the declared paths", legacyCert, legacyKey)
}

// copyDiskFile copies one file with exact permissions.
func copyDiskFile(src, dst string, mode os.FileMode) error {
	raw, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, raw, mode)
}
