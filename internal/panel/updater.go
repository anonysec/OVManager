package panel

import (
	"encoding/json"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/version"
)

// Panel update checker (backend).
//
// The panel never downloads or installs anything: /status only reads GitHub's
// public release API (fail-soft, so an unreachable GitHub never turns the
// health page into an error), and /run hands the work to the installer that
// already owns it. Docker installs have no installer inside the container, so
// /run answers with the exact host-side command instead.

const (
	updaterDefaultAppDir = "/opt/ovmanager"
	updaterDefaultRepo   = "anonysec/OVManager"

	updaterHTTPTimeout = 5 * time.Second
	updaterCacheTTL    = 3600.0
	updateLogName      = "update.log"

	hostComposeCmd      = "docker compose up -d --build"
	hostRestartCmd      = "docker restart ovmanager"
	hostNativeUpdateCmd = "sudo ovmanager update"
)

// updateCache is updater.py's module-level _cache (1h TTL, process-wide).
var updateCache = struct {
	mu     sync.Mutex
	ts     float64
	latest string
	source string
	note   string
}{source: "unknown"}

// updaterAppDir is _app_dir(): the installer location, defaulting to
// /opt/ovmanager — deliberately not appDir()'s cwd fallback.
func updaterAppDir() string {
	dir := os.Getenv("OVM_APP_DIR")
	if dir == "" {
		dir = updaterDefaultAppDir
	}
	if strings.HasPrefix(dir, "~") {
		if home, err := os.UserHomeDir(); err == nil {
			rest := strings.TrimPrefix(dir[1:], "/")
			dir = filepath.Join(home, rest)
		}
	}
	return dir
}

// updaterRepo is _repo(): "owner/name" upstream (OVM_REPO override).
func updaterRepo() string {
	if repo := strings.TrimSpace(os.Getenv("OVM_REPO")); repo != "" {
		return repo
	}
	return updaterDefaultRepo
}

func inContainer() bool { return fileExists("/.dockerenv") }

func hasSystemctl() bool {
	_, err := exec.LookPath("systemctl")
	return err == nil
}

var versionNumRe = regexp.MustCompile(`^(\d+(?:\.\d+)*)`)

// versionKey is _version_key: "v2.10.1-rc1" -> [2 10 1]. Digits must lead, so
// non-version tags ("nightly") yield an empty key and never look newer.
func versionKey(value string) []int {
	raw := strings.TrimLeft(strings.TrimSpace(value), "vV")
	match := versionNumRe.FindStringSubmatch(raw)
	if match == nil {
		return nil
	}
	parts := strings.Split(match[1], ".")
	out := make([]int, 0, len(parts))
	for _, part := range parts {
		n, _ := strconv.Atoi(part)
		out = append(out, n)
	}
	return out
}

// versionNewer is _is_newer: tuple comparison, shorter prefix loses.
func versionNewer(latest, current string) bool {
	if latest == "" {
		return false
	}
	a, b := versionKey(latest), versionKey(current)
	for i := 0; i < len(a) || i < len(b); i++ {
		var x, y int
		if i < len(a) {
			x = a[i]
		}
		if i < len(b) {
			y = b[i]
		}
		if x != y {
			return x > y
		}
	}
	return false
}

// fetchLatest is _fetch_latest: returns (tag, source, note); never raises.
func fetchLatest(repo string) (string, string, string) {
	const networkNote = "Could not reach GitHub (network error or rate limit)."
	client := &http.Client{Timeout: updaterHTTPTimeout}
	get := func(url string) ([]byte, int, error) {
		req, err := http.NewRequest(http.MethodGet, url, nil)
		if err != nil {
			return nil, 0, err
		}
		req.Header.Set("Accept", "application/vnd.github+json")
		req.Header.Set("User-Agent", "OVManager/"+version.Version)
		resp, err := client.Do(req)
		if err != nil {
			return nil, 0, err
		}
		defer resp.Body.Close()
		raw, _ := readAtMost(resp.Body, 1<<20)
		return raw, resp.StatusCode, nil
	}

	api := "https://api.github.com/repos/" + repo
	raw, code, err := get(api + "/releases/latest")
	if err != nil {
		return "", "unknown", networkNote
	}
	if code == 200 {
		var body map[string]any
		if json.Unmarshal(raw, &body) == nil {
			if tag, _ := body["tag_name"].(string); tag != "" {
				return strings.TrimSpace(tag), "github", ""
			}
		}
	}
	raw, code, err = get(api + "/tags")
	if err != nil {
		return "", "unknown", networkNote
	}
	if code == 200 {
		var tags []map[string]any
		if json.Unmarshal(raw, &tags) == nil && len(tags) > 0 {
			// GitHub returns tags newest-first, but not always (git push order
			// leaks through): pick the highest version instead of tags[0].
			// versionNewer ignores non-version tags ("nightly"), so a tag-less
			// push order still falls back to the first entry.
			best := ""
			for _, tag := range tags {
				name, _ := tag["name"].(string)
				name = strings.TrimSpace(name)
				if name == "" {
					continue
				}
				if best == "" || versionNewer(name, best) {
					best = name
				}
			}
			if best != "" {
				return best, "github", ""
			}
		}
	}
	return "", "unknown", "GitHub did not report any release or tag."
}

// latestCached is _latest_cached: the latest tag plus its checked-at epoch.
func latestCached(repo string) (string, string, string, int64) {
	now := float64(time.Now().UnixNano()) / 1e9
	updateCache.mu.Lock()
	defer updateCache.mu.Unlock()
	if updateCache.ts != 0 && now-updateCache.ts < updaterCacheTTL {
		return updateCache.latest, updateCache.source, updateCache.note, int64(updateCache.ts)
	}
	latest, source, note := fetchLatest(repo)
	updateCache.ts, updateCache.latest, updateCache.source, updateCache.note = now, latest, source, note
	return latest, source, note, int64(now)
}

// updateStatus is GET /updater/status. Fail-soft: success is always true.
func (h *Handler) updateStatus(w http.ResponseWriter, r *http.Request) {
	latest, source, note, checkedAt := latestCached(updaterRepo())
	var latestValue any
	if latest != "" {
		latestValue = latest
	}
	data := map[string]any{
		"current":          version.Version,
		"latest":           latestValue,
		"update_available": versionNewer(latest, version.Version),
		"source":           source,
		"checked_at":       checkedAt,
	}
	if note != "" {
		data["note"] = note
	}
	msg := note
	if msg == "" {
		msg = "Update status"
	}
	envelope(w, true, msg, data)
}

// updateOperation is GET /updater/operation: the persisted host-side update
// transaction state.
func (h *Handler) updateOperation(w http.ResponseWriter, r *http.Request) {
	statePath := filepath.Join(dataDir(), "update-state.json")
	if !fileExists(statePath) {
		envelope(w, true, "No update transaction recorded", nil)
		return
	}
	raw, err := os.ReadFile(statePath) // #nosec G304 // triaged intentional
	if err != nil {
		envelope(w, false, "The update state file is unreadable", nil)
		return
	}
	var decoded map[string]any
	if json.Unmarshal(raw, &decoded) != nil {
		envelope(w, false, "The update state file is unreadable", nil)
		return
	}
	allowed := map[string]any{}
	for _, key := range []string{"phase", "from_version", "to_version", "safety_backup", "updated_at", "pid"} {
		allowed[key] = decoded[key]
	}
	allowed["maintenance"] = fileExists(filepath.Join(dataDir(), "update-maintenance"))
	phase, _ := decoded["phase"].(string)
	allowed["finished"] = phase == "committed" || phase == "failed_over"
	envelope(w, true, "Update transaction state", allowed)
}

// runUpdate is POST /updater/run: start the installer in the background, or
// explain the host-side command.
func (h *Handler) runUpdate(w http.ResponseWriter, r *http.Request) {
	installSh := filepath.Join(updaterAppDir(), "install.sh")
	container := inContainer()
	if !container && os.Geteuid() == 0 && fileExists(installSh) && hasSystemctl() {
		h.startNativeUpdate(w, installSh)
		return
	}

	var reason string
	switch {
	case container:
		reason = "The panel is running inside a container, so it cannot update itself."
	case os.Geteuid() != 0:
		reason = "The panel runs as an unprivileged service account, so it cannot replace itself."
	case !fileExists(installSh):
		reason = "The installer was not found at " + installSh + "."
	default:
		reason = "systemctl was not found, so the service cannot be restarted automatically."
	}
	mode, command, msg := "manual", hostNativeUpdateCmd,
		reason+" From the host, run: "+hostNativeUpdateCmd+"."
	if container {
		mode = "docker"
		command = hostComposeCmd
		msg = reason + " From the host, run: " + hostComposeCmd + " (or " + hostRestartCmd + ")."
	}
	envelope(w, false, msg, map[string]any{
		"mode": mode, "command": command, "restart_command": hostRestartCmd,
	})
}

// startNativeUpdate detaches `bash <install_sh> update` and returns immediately.
func (h *Handler) startNativeUpdate(w http.ResponseWriter, installSh string) {
	logPath := filepath.Join(dataDir(), updateLogName)
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil { // #nosec G301 // triaged intentional
		envelope(w, false, "Could not start the updater: "+err.Error(), nil)
		return
	}
	logFile, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644) // #nosec G304 // triaged intentional G302
	if err != nil {
		envelope(w, false, "Could not start the updater: "+err.Error(), nil)
		return
	}
	defer logFile.Close()

	cmd := exec.Command("bash", installSh, "update") // #nosec G204 // triaged intentional
	cmd.Stdin = nil
	cmd.Stdout = logFile
	cmd.Stderr = logFile // stderr=subprocess.STDOUT
	cmd.SysProcAttr = detachSysProcAttr()
	if err := cmd.Start(); err != nil {
		envelope(w, false, "Could not start the updater: "+err.Error(), nil)
		return
	}
	_ = cmd.Process.Release()

	envelope(w, true, "Update started. The panel will restart in a moment.", map[string]any{
		"command":          "bash " + installSh + " update",
		"log":              logPath,
		"previous_version": version.Version,
	})
}
