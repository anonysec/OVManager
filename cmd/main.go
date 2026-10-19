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

	// The panel prefix is resolved per request (5s DB cache) so a URL-path
	// change in Settings takes effect without a restart.
	root.Handle("/", panelDispatcher(h))

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

// panelDispatcher routes the site root: the current panel prefix serves the
// SPA (bare prefix redirects to the trailing slash), everything else gets the
// decoy 404. The prefix is resolved per request.
func panelDispatcher(h *panel.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		prefix := "/" + strings.Trim(h.URLPath(), "/")
		if prefix == "/" {
			prefix = "/dashboard"
		}
		p := r.URL.Path
		if p == prefix {
			http.Redirect(w, r, prefix+"/", http.StatusMovedPermanently)
			return
		}
		if strings.HasPrefix(p, prefix+"/") {
			spaHandler(h).ServeHTTP(w, r)
			return
		}
		decoyHandler().ServeHTTP(w, r)
	})
}

// spaHandler serves the built web and falls back to index.html for the
// client-side router. Reserved prefixes answer 404 like app.py's catch-all,
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
		if basePath == "/" {
			basePath = "/dashboard"
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
		if rel == "" || rel == basePath {
			rel = "index.html"
		}
		if rel != "index.html" {
			if _, err := fs.Stat(fsys, filepath.ToSlash(rel)); err == nil {
				http.StripPrefix(prefix, fileServer).ServeHTTP(w, r)
				return
			}
		}
		index, err := fs.ReadFile(fsys, "index.html")
		if err != nil {
			http.NotFound(w, r)
			return
		}
		html := string(index)
		bp := basePath
		if !strings.HasSuffix(bp, "/") {
			bp += "/"
		}
		if !strings.Contains(html, "<base") {
			html = strings.Replace(html, "<head>", "<head><base href=\""+bp+"\">", 1)
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(html))
	})
}

// decoyHandler serves a generic placeholder at the site root so the panel is
// never reachable from "/".
func decoyHandler() http.Handler {
	page := `<!doctype html><html><head><meta charset="utf-8"><title>404 Not Found</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#0B0B10;overflow:hidden;font-family:'Share Tech Mono',monospace;color:#F8FAFC}
canvas{position:fixed;inset:0;z-index:0;opacity:.35}
.scanlines{position:fixed;inset:0;z-index:2;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,0.12) 0px,rgba(0,0,0,0.12) 1px,transparent 1px,transparent 4px)}
.vignette{position:fixed;inset:0;z-index:1;pointer-events:none;background:radial-gradient(circle,rgba(0,0,0,0)_55%,rgba(0,0,0,0.9)_100%)}
.overlay{position:fixed;inset:0;z-index:3;display:grid;place-items:center;text-align:center;pointer-events:none}
.hud{border:1px solid #1E293B;padding:2.5rem 3.5rem;background:rgba(30,30,35,0.6);backdrop-filter:blur(6px);box-shadow:0 0 24px rgba(59,130,246,0.25)}
.code{font-family:'Fira Code',monospace;font-size:.8rem;color:#94A3B8;letter-spacing:.15em;margin-bottom:1rem}
.glitch{font-size:clamp(4rem,12vw,9rem);font-weight:400;color:#F8FAFC;letter-spacing:.1em;text-shadow:0 0 12px #3B82F6,0 0 30px #3B82F6;animation:scan 2s linear infinite}
.sub{margin-top:1rem;font-size:.85rem;letter-spacing:.25em;color:#94A3B8;text-transform:uppercase}
.sub span{color:#3B82F6}
.ticker{position:fixed;bottom:1rem;left:1rem;right:1rem;z-index:3;font-size:.7rem;color:#94A3B8;letter-spacing:.1em;display:flex;justify-content:space-between;pointer-events:none}
@keyframes scan{0%,100%{opacity:1}50%{opacity:.7}}
@media (prefers-reduced-motion:reduce){.glitch{animation:none}}
</style></head><body>
<canvas id="c"></canvas>
<div class="scanlines"></div>
<div class="vignette"></div>
<div class="overlay"><div class="hud"><div class="code">ERR::NOT_FOUND</div><div class="glitch">404</div><div class="sub">resource<span>//</span>missing</div></div></div>
<div class="ticker"><span>SYS.STATUS: ONLINE</span><span>SEC.LEVEL: MAX</span><span>UPTIME: 99.99%</span></div>
<script>
const c=document.getElementById('c'),ctx=c.getContext('2d');
function resize(){c.width=innerWidth;c.height=innerHeight}
resize();addEventListener('resize',resize);
const chars='01ABCDEF<>{}[]|/\';
const fs=14,cols=Math.floor(c.width/fs),drops=Array(cols).fill(1);
const pal=['#3B82F6','#60A5FA','#94A3B8','#F8FAFC'];
function draw(){
  ctx.fillStyle='rgba(11,11,16,0.08)';ctx.fillRect(0,0,c.width,c.height);
  ctx.font=fs+'px "Share Tech Mono",monospace';
  for(let i=0;i<drops.length;i++){
    ctx.fillStyle=pal[Math.floor(Math.random()*pal.length)];
    ctx.shadowColor=ctx.fillStyle;ctx.shadowBlur=6;
    const t=chars[Math.floor(Math.random()*chars.length)];
    ctx.fillText(t,i*fs,drops[i]*fs);
    if(drops[i]*fs>c.height&&Math.random()>.98) drops[i]=0;
    drops[i]++;
  }
}
setInterval(draw,50);
</script></body></html>`
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(page))
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
