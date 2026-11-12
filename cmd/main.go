// Command ovmanager is the OVManager panel binary and operator CLI (Phase 5).
// Run bare (or via systemd) it serves the panel; with a subcommand it acts as
// the `ovmanager` operator CLI.
package main

import (
	"context"
	"crypto/tls"
	"errors"
	"html"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/cli"
	"github.com/anonysec/OVManager/internal/db"
	"github.com/anonysec/OVManager/internal/health"
	"github.com/anonysec/OVManager/internal/node"
	"github.com/anonysec/OVManager/internal/panel"
	"github.com/anonysec/OVManager/internal/telemetry"
	"github.com/anonysec/OVManager/internal/users"
	"github.com/anonysec/OVManager/internal/version"
	"github.com/anonysec/OVManager/internal/webfs"
)

func main() {
	if len(os.Args) > 1 {
		os.Exit(cli.Run(os.Args[1:], os.Stdout))
	}
	os.Exit(run())
}

func run() int {
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	dataDir := env("DataDir", node.DataDir)
	cfg := db.ConfigFromEnv()
	if cfg.Path == "" {
		cfg.Path = filepath.Join(dataDir, "app.db")
	}
	conn, err := db.OpenConfig(cfg)
	if err != nil {
		log.Printf("open database: %v", err)
		return 1
	}
	defer func() { _ = conn.Close() }()
	if _, err := db.Migrate(conn); err != nil {
		log.Printf("migrate database: %v", err)
		return 1
	}
	port := env("Port", "2095")
	certFile := panel.SSLCertPath()
	keyFile := panel.SSLKeyPath()
	tlsEnabled := fileExists(certFile) && fileExists(keyFile)
	svc := auth.NewService(conn, dataDir)
	handler := panelRouter(svc)
	addr, useTLS := serveMode(tlsEnabled, port)
	if !useTLS {
		log.Printf("SECURITY WARNING: panel is serving over HTTP without TLS; session cookies are Secure and will be blocked by browsers.")
	}
	srv := newServer(addr, handler)
	if useTLS {
		srv.TLSConfig = &tls.Config{
			GetCertificate: panel.ReloadingCertificate(certFile, keyFile),
			MinVersion:     tls.VersionTLS12,
		}
	}
	srvErr := make(chan error, 1)
	go func() {
		if useTLS {
			log.Printf("ovmanager-go %s listening on https://%s (TLS)", version.Version, addr)
			srvErr <- srv.ListenAndServeTLS(certFile, keyFile)
		} else {
			log.Printf("ovmanager-go %s listening on http://%s (no TLS)", version.Version, addr)
			srvErr <- srv.ListenAndServe()
		}
	}()
	select {
	case err := <-srvErr:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("listen %s: %v", addr, err)
			return 1
		}
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := srv.Shutdown(shutdownCtx); err != nil {
			log.Printf("shutdown: %v", err)
			return 1
		}
	}
	return 0
}

// panelRouter assembles the panel surface: root /health, every router under
// /api, the unprefixed subscription page, and the built SPA as the fallback.
func panelRouter(svc *auth.Service) http.Handler {
	h := panel.NewHandler(svc)

	api := http.NewServeMux()
	svc.Mount(api)
	users.NewHandler(svc).Mount(api)
	nodeH := node.NewHandler(svc)
	nodeH.OnNodeChange = func(op string) {
		telemetry.Publish("nodes", telemetry.KV{Key: "op", Val: op})
	}
	nodeH.Mount(api)
	telemetry.NewHandler(svc).Mount(api)
	h.Mount(api)
	h.MountLogs(api)

	root := http.NewServeMux()
	root.Handle("/health", health.Router())
	root.Handle("/api/", http.StripPrefix("/api", api))
	root.Handle("/api", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	api.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Empty 404 for unmatched paths; method mismatches keep ServeMux 405.
		if r.Method != http.MethodGet && r.Method != http.MethodPost && r.Method != http.MethodPut && r.Method != http.MethodPatch && r.Method != http.MethodDelete {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if strings.HasPrefix(r.URL.Path, "/login") || strings.HasPrefix(r.URL.Path, "/logout") {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	_ = api

	spa := spaHandler(h)
	root.Handle("/", panelDispatcher(h, spa))

	// Track active requests so a database restore can drain in-flight
	// requests before swapping the live pool.
	wrapped := h.TrackActive(root)

	return panel.SecurityHeaders(wrapped)
}

// appDir is where .env and web/ live (backend config app_dir).
func appDir() string {
	if d := os.Getenv("OVM_APP_DIR"); d != "" {
		return d
	}
	if wd, err := os.Getwd(); err == nil {
		return wd
	}
	return "."
}

// panelDispatcher routes the site root: the current panel prefix serves the
// SPA (bare prefix redirects to the trailing slash), everything else gets the
// decoy 404. The prefix is resolved per request.
func panelDispatcher(h *panel.Handler, spa http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		prefix := "/" + strings.Trim(h.URLPath(), "/")
		isRoot := prefix == "/" || prefix == "//"
		p := r.URL.Path
		if isRoot {
			spa.ServeHTTP(w, r)
			return
		}
		if p == "/" {
			decoyHandler().ServeHTTP(w, r)
			return
		}
		if p == prefix {
			http.Redirect(w, r, prefix+"/", http.StatusMovedPermanently)
			return
		}
		if strings.HasPrefix(p, prefix+"/") {
			spa.ServeHTTP(w, r)
			return
		}
		h.SubHandler().ServeHTTP(w, r)
	})
}

func isAssetPath(path string) bool {
	return path == "sw.js" || path == "favicon.ico" || path == "manifest.webmanifest" || strings.HasPrefix(path, "assets/") || strings.HasPrefix(path, "icons/") || strings.HasPrefix(path, "fonts/")
}

func serveIndex(w http.ResponseWriter, r *http.Request, index []byte, basePath string) {
	htmlContent := string(index)
	bp := basePath
	if !strings.HasSuffix(bp, "/") {
		bp += "/"
	}
	if !strings.Contains(htmlContent, "<base") {
		htmlContent = strings.Replace(htmlContent, "<head>", "<head><base href=\""+html.EscapeString(bp)+"\">", 1)
	}
	if nonce := panel.NonceFromContext(r.Context()); nonce != "" {
		htmlContent = strings.ReplaceAll(htmlContent, "<script>", `<script nonce="`+nonce+`">`)
		htmlContent = strings.ReplaceAll(htmlContent, "<script type=\"module\"", `<script nonce="`+nonce+`" type="module"`)
	}
	w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = w.Write([]byte(htmlContent))
}

// client-side router. Reserved prefixes answer 404 like the catch-all,
// never SPA HTML.
//
// The SPA comes from <appDir>/web/dist when that tree exists (a dev checkout,
// or an explicit OVM_APP_DIR); otherwise — a release install ships only the
// binary — it is served from the copy embedded via internal/webfs.
func spaHandler(h *panel.Handler) http.Handler {
	var fsys fs.FS = webfs.Dist()
	if dist := filepath.Join(appDir(), "web", "dist"); diskIndex(dist) {
		fsys = os.DirFS(dist)
	}
	return spaHandlerWithFS(h, fsys)
}

func spaHandlerWithFS(h *panel.Handler, fsys fs.FS) http.Handler {
	fileServer := http.FileServer(http.FS(fsys))
	index, _ := fs.ReadFile(fsys, "index.html")
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		basePath := "/" + strings.Trim(h.URLPath(), "/")
		isRoot := basePath == "/" || basePath == "//"
		if isRoot {
			basePath = "/"
		}
		path := strings.TrimPrefix(r.URL.Path, "/")
		if path == "doc" || path == "openapi.json" {
			http.NotFound(w, r)
			return
		}
		if r.Method != http.MethodGet {
			http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
			return
		}
		prefix := basePath + "/"
		rel := strings.TrimPrefix(r.URL.Path, prefix)
		if isRoot {
			rel = strings.TrimPrefix(r.URL.Path, "/")
		}
		if rel == "" || rel == basePath {
			rel = "index.html"
		}
		if rel != "index.html" {
			if _, err := fs.Stat(fsys, filepath.ToSlash(rel)); err != nil {
				candidate := strings.TrimSuffix(rel, "/")
				if _, fileErr := fs.Stat(fsys, filepath.ToSlash(candidate)); fileErr != nil {
					if !isAssetPath(rel) {
						if len(index) == 0 {
							w.WriteHeader(http.StatusNotFound)
							return
						}
						serveIndex(w, r, index, basePath)
						return
					}
					w.WriteHeader(http.StatusNotFound)
					return
				}
				rel = candidate
			}
			if _, err := fs.Stat(fsys, filepath.ToSlash(rel)); err == nil {
				if rel == "sw.js" {
					w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
				} else if strings.HasPrefix(rel, "assets/") || strings.HasPrefix(rel, "icons/") || strings.HasPrefix(rel, "fonts/") {
					w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
				}
				if isRoot {
					fileServer.ServeHTTP(w, r)
				} else {
					http.StripPrefix(prefix, fileServer).ServeHTTP(w, r)
				}
				return
			}
		}
		if len(index) == 0 {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		serveIndex(w, r, index, basePath)
	})
}

// decoyHandler serves a generic placeholder at the site root so the panel is
// never reachable from "/".
func decoyHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
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
// plaintext binds loopback unless HOST says otherwise; TLS binds all
// interfaces.
//
// A native install writes Host=127.0.0.1 (install.sh), so it stays on
// loopback behind a reverse proxy.
func serveMode(tlsEnabled bool, port string) (string, bool) {
	host := "127.0.0.1"
	if tlsEnabled {
		host = "0.0.0.0"
	} else if h := strings.TrimSpace(env("Host", "")); h != "" {
		host = h
	}
	return net.JoinHostPort(host, port), tlsEnabled
}

func newServer(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
}

func fileExists(p string) bool {
	if p == "" {
		return false
	}
	info, err := os.Stat(p)
	return err == nil && !info.IsDir()
}
