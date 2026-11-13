// Package audit writes the panel's audit trail: one JSONL line per state-changing
// operation, attributed to the actor who performed it. File-based (not DB).
package audit

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

var (
	mu       sync.Mutex
	idSeq    int64
	seqOnce  sync.Once
	auditDir = "/var/log/ovmanager"
	// warnOnce keeps a broken audit path to one log line per process: the
	// panel audits on every state change, so repeating the failure would
	// drown the journal it is trying to preserve.
	warnOnce sync.Once
)

// warnFailure surfaces an unwritable audit trail once. Silently dropping
// audit lines was how an empty Logs page went unnoticed for days.
func warnFailure(op, path string, err error) {
	if err == nil {
		return
	}
	warnOnce.Do(func() {
		log.Printf("audit: cannot %s %s: %v — audit entries are being dropped (check ownership of %s)",
			op, path, err, filepath.Dir(path))
	})
}

// PathEnv names the environment variable that overrides the audit file
// location. The default sits under /var/log.
const PathEnv = "OVMANAGER_AUDIT_PATH"

// Path returns the audit file path. The primary location is /var/log; when
// that directory is not writable by the panel (a service started before the
// unit owned it, or a root CLI that created it 0700), the trail falls back to
// DataDir/audit.jsonl — the same user owns both, so the fallback always works
// and the Logs page keeps reading the file the service actually writes.
func Path() string {
	if p := strings.TrimSpace(os.Getenv(PathEnv)); p != "" {
		return p
	}
	pathOnce.Do(resolveDefaultPath)
	return defaultPath
}

var (
	pathOnce    sync.Once
	defaultPath string
)

func resolveDefaultPath() {
	primary := filepath.Join(auditDir, "audit.jsonl")
	fallback := filepath.Join(dataDir(), "audit.jsonl")
	// Sticky: once the service has used the fallback, every process (root CLI
	// included) keeps reading and writing the same file.
	if _, err := os.Stat(fallback); err == nil {
		defaultPath = fallback
		return
	}
	if writableDir(auditDir) {
		defaultPath = primary
		return
	}
	defaultPath = fallback
	log.Printf("audit: %s is not writable; writing the trail to %s", auditDir, fallback)
}

// writableDir reports whether this process can create files in dir.
func writableDir(dir string) bool {
	if err := os.MkdirAll(dir, 0o750); err != nil {
		return false
	}
	f, err := os.CreateTemp(dir, ".audit-probe-*")
	if err != nil {
		return false
	}
	name := f.Name()
	_ = f.Close()
	_ = os.Remove(name)
	return true
}

// dataDir returns the panel data dir (env first, released default otherwise).
func dataDir() string {
	if v := strings.TrimSpace(os.Getenv("DataDir")); v != "" {
		return v
	}
	return "/var/lib/ovmanager"
}

// Record writes one audit line. actor is the authenticated username; an empty
// actor is stored as "system". meta must never carry a secret.
func Record(db interface{}, actor, kind, severity, message string, meta map[string]any) {
	if meta == nil {
		meta = map[string]any{}
	}
	mu.Lock()
	defer mu.Unlock()
	seqOnce.Do(loadIDSeq)
	idSeq++
	payload := map[string]any{
		"id":       idSeq,
		"ts":       float64(time.Now().Unix()),
		"actor":    strings.TrimSpace(actor),
		"action":   kind,
		"severity": severity,
		"message":  message,
		"meta":     meta,
		"promoted": false,
	}
	if payload["actor"] == "" {
		payload["actor"] = "system"
	}
	if t, ok := meta["target"].(string); ok && t != "" {
		payload["target"] = t
	}
	line, err := json.Marshal(payload)
	if err != nil {
		return
	}
	payload["detail"] = string(line)
	line, err = json.Marshal(payload)
	if err != nil {
		return
	}
	path := Path()
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0o750); err != nil {
		warnFailure("create directory", path, err)
		return
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o640) // #nosec G304,G302 -- operator path or fixed default; group read is intentional
	if err != nil {
		warnFailure("open", path, err)
		return
	}
	defer f.Close()
	if os.Geteuid() == 0 {
		// Root-run CLI commands (reset-password, claim) audit too. Hand the
		// file to the directory's owner so the service user can keep appending
		// instead of being locked out by a root:root 0600 file.
		if info, err := os.Stat(dir); err == nil {
			if st, ok := info.Sys().(*syscall.Stat_t); ok {
				if os.Geteuid() == 0 && (int(st.Uid) != 0 || int(st.Gid) != 0) {
					_ = f.Chown(int(st.Uid), int(st.Gid))
				}
			}
		}
		_ = f.Chmod(0o640)
	}
	_, _ = fmt.Fprintf(f, "%s\n", line)
}

// ReadLines returns all audit lines parsed as maps.
func ReadLines() []map[string]any {
	data, err := os.ReadFile(Path())
	if err != nil {
		return nil
	}
	var out []map[string]any
	for _, line := range strings.Split(string(data), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var obj map[string]any
		if json.Unmarshal([]byte(line), &obj) == nil {
			out = append(out, obj)
		}
	}
	return out
}

// Prune drops entries older than cutoff. The rewrite holds the same lock as
// Record, so an append during the pass is not lost; the temp file and rename
// keep a crash from leaving a truncated trail.
func Prune(cutoff float64) int {
	mu.Lock()
	defer mu.Unlock()
	return pruneFile(Path(), cutoff)
}

func pruneFile(path string, cutoff float64) int {
	data, err := os.ReadFile(path) // #nosec G304 -- operator-set audit path or a fixed default
	if err != nil {
		return 0
	}
	var kept []string
	removed := 0
	for _, line := range strings.Split(string(data), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var obj map[string]any
		if json.Unmarshal([]byte(line), &obj) != nil {
			kept = append(kept, line)
			continue
		}
		ts, _ := obj["ts"].(float64)
		if ts < cutoff {
			removed++
			continue
		}
		kept = append(kept, line)
	}
	if removed == 0 {
		return 0
	}
	out := strings.Join(kept, "\n")
	if len(kept) > 0 {
		out += "\n"
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".audit-prune-*")
	if err != nil {
		return 0
	}
	name := tmp.Name()
	defer func() { _ = os.Remove(name) }()
	if err := tmp.Chmod(0o640); err != nil {
		_ = tmp.Close()
		return 0
	}
	if _, err := tmp.WriteString(out); err != nil {
		_ = tmp.Close()
		return 0
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return 0
	}
	if err := tmp.Close(); err != nil {
		return 0
	}
	if err := os.Rename(name, path); err != nil {
		return 0
	}
	return removed
}

// MarkPromoted sets promoted=true for the given id in the file.
func MarkPromoted(id int64) {
	mu.Lock()
	defer mu.Unlock()
	data, err := os.ReadFile(Path())
	if err != nil {
		return
	}
	lines := strings.Split(string(data), "\n")
	var out []string
	for _, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var obj map[string]any
		if json.Unmarshal([]byte(line), &obj) != nil {
			out = append(out, line)
			continue
		}
		if v, ok := obj["id"].(float64); ok && int64(v) == id {
			obj["promoted"] = true
			b, _ := json.Marshal(obj)
			out = append(out, string(b))
		} else {
			out = append(out, line)
		}
	}
	_ = os.WriteFile(Path(), []byte(strings.Join(out, "\n")+"\n"), 0o600) // #nosec G703 // Path is the operator-set OVMANAGER_AUDIT_PATH or a fixed default
}

// loadIDSeq seeds the id counter from the existing file, so ids stay
// monotonic across a restart.
func loadIDSeq() {
	for _, obj := range ReadLines() {
		if v, ok := obj["id"].(float64); ok {
			if int64(v) > idSeq {
				idSeq = int64(v)
			}
		}
	}
}
