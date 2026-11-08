// Command ovmanager is the OVManager panel binary and operator CLI (Phase 5).
// Run bare (or via systemd) it serves the panel; with a subcommand it acts as
// the `ovmanager` operator CLI.
package main

import (
	"html"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

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
	cfg := db.ConfigFromEnv()
	if cfg.Path == "" && cfg.URL == "" {
		cfg.Path = filepath.Join(dataDir, "ovmanager.db")
	}
	conn, err := db.OpenConfig(cfg)
	if err != nil {
		log.Fatalf("open database: %v", err)
	}
	defer conn.Close()
	if _, err := db.MigrateWithBackend(conn, cfg.Backend()); err != nil {
		log.Fatalf("migrate database: %v", err)
	}

	port := env("PORT", "2095")
	migrateLegacyTLS(dataDir)
	certFile := panel.SSLCertPath()
	keyFile := panel.SSLKeyPath()
	tlsEnabled := fileExists(certFile) && fileExists(keyFile)

	svc := auth.NewService(conn, dataDir)
	// The flag is read from the process environment inside NewService; the
	// panel's .env is consulted too, so a panel started by hand next to its
	// .env trusts the proxy the same way a systemd or container one does.
	svc.TrustedProxy = svc.TrustedProxy || panel.TrustedProxyEnabled()
	handler := panelRouter(svc)

	addr, useTLS := serveMode(tlsEnabled, port)
	if svc.TrustedProxy && (strings.HasPrefix(addr, "0.0.0.0:") || strings.HasPrefix(addr, ":")) {
		log.Printf("SECURITY WARNING: TRUSTED_PROXY is enabled while binding to public address %s. Direct connections could spoof headers unless behind a firewall/proxy!", addr)
	}
	srv := newServer(addr, handler)
	if useTLS {
		log.Printf("ovmanager-go %s listening on https://%s (TLS)", version.Version, addr)
		if err := srv.ListenAndServeTLS(certFile, keyFile); err != nil {
			log.Fatalf("listen %s: %v", addr, err)
		}
	} else {
		if !svc.TrustedProxy {
			log.Printf("SECURITY WARNING: panel is serving over HTTP without TLS; session cookies are Secure and will be blocked by browsers - configure TLS or set TRUSTED_PROXY behind an HTTPS proxy")
		}
		log.Printf("ovmanager-go %s listening on http://%s (no TLS)", version.Version, addr)
		if err := srv.ListenAndServe(); err != nil {
			log.Fatalf("listen %s: %v", addr, err)
		}
	}
}

type blankHandler struct{ http.Handler }

func (h blankHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.Handler.ServeHTTP(blankWriter{ResponseWriter: w}, r)
}

type blankWriter struct{ http.ResponseWriter }

func (w blankWriter) Write(p []byte) (int, error) {
	return len(p), nil
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
	root.Handle("/health", health.Router(panel.TrustedProxyEnabled()))
	root.Handle("/api/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.StripPrefix("/api", blankHandler{Handler: api}).ServeHTTP(w, r)
	}))
	root.Handle("/api", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))

	// The panel prefix is resolved per request (5s DB cache) so a URL-path
	// change in Settings takes effect without a restart.
	root.Handle("/", panelDispatcher(h))

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
func panelDispatcher(h *panel.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		prefix := "/" + strings.Trim(h.URLPath(), "/")
		isRoot := prefix == "/" || prefix == "//"
		p := r.URL.Path
		if isRoot {
			spaHandler(h).ServeHTTP(w, r)
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
			spaHandler(h).ServeHTTP(w, r)
			return
		}
		h.SubHandler().ServeHTTP(w, r)
	})
}

func isAssetPath(path string) bool {
	return path == "sw.js" || strings.HasPrefix(path, "assets/") || strings.HasPrefix(path, "icons/") || strings.HasPrefix(path, "fonts/")
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
	fileServer := http.FileServer(http.FS(fsys))
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
						index, err := fs.ReadFile(fsys, "index.html")
						if err != nil {
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
		index, err := fs.ReadFile(fsys, "index.html")
		if err != nil {
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
// A native install writes HOST=127.0.0.1 (install.sh), so it stays on
// loopback behind a reverse proxy.
func serveMode(tlsEnabled bool, port string) (string, bool) {
	host := "127.0.0.1"
	if tlsEnabled {
		host = "0.0.0.0"
	} else if h := strings.TrimSpace(env("HOST", "")); h != "" {
		host = h
	}
	return net.JoinHostPort(host, port), tlsEnabled
}

// newServer builds the panel's http.Server with bounded read/idle timeouts.
// WriteTimeout is deliberately left at 0: the SSE stream is a long-lived
// response and a global write deadline would kill every live stream (the
// stream sets its own per-write deadline).
//
// ReadHeaderTimeout is the slowloris guard — headers must arrive quickly.
// ReadTimeout covers the whole request BODY, so it is generous: the restore
// endpoint accepts a 100 MB database upload, which on a slow uplink takes
// minutes. The body SIZE is bounded separately, per endpoint, by
// http.MaxBytesReader.
func newServer(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       10 * time.Minute,
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

// migrateLegacyTLS copies the pre-declaration pair in DATA_DIR/tls onto the
// declared paths when the declared ones are empty, so an install that keeps
// its certificate in the legacy location does not silently fall back to plain
// HTTP after the restart that lands TLS resolution (tls migrate_legacy_tls).
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
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
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
	raw, err := os.ReadFile(src) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return err
	}
	return os.WriteFile(dst, raw, mode) // #nosec // src/dst from internal staging paths
}
