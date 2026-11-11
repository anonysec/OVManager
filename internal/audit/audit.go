// Package audit writes the panel's audit trail: one JSONL line per state-changing
// operation, attributed to the actor who performed it. File-based (not DB).
package audit

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

var (
	mu       sync.Mutex
	idSeq    int64
	seqOnce  sync.Once
	auditDir = "/var/log/ovmanager"
)

// PathEnv names the environment variable that overrides the audit file
// location. The default sits under /var/log.
const PathEnv = "OVMANAGER_AUDIT_PATH"

// Path returns the audit file path.
func Path() string {
	if p := strings.TrimSpace(os.Getenv(PathEnv)); p != "" {
		return p
	}
	return filepath.Join(auditDir, "audit.jsonl")
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
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600) // #nosec G304 // path is the operator-set OVMANAGER_AUDIT_PATH or a fixed default
	if err != nil {
		return
	}
	defer f.Close()
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
