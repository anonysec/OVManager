// GET /logs — journal tail for the panel and its nodes (plan Task 2).
//
// The unit is whitelisted: "ovmanager" for the panel itself, "openvpn-<name>"
// for every row in the nodes table (the unit name is derived from the node
// name only). Anything else — and anything outside [a-z0-9@._-] — is a 400
// before journalctl is ever spawned, and the argv besides the unit/lines pair
// is static, so no user input reaches a shell.
package panel

import (
	"net/http"
	"os/exec"
	"regexp"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/go/internal/auth"
)

const (
	logsDetailUnknownUnit = "Unknown unit (allowed: ovmanager, openvpn-<name>)"
	logsDetailUnreadable  = "journalctl unreadable (add the panel user to systemd-journal)"
	logsDetailMissing     = "journalctl is not installed on this host"
	logsDetailFailed      = "journalctl produced an error"
	logsDefaultLines      = 200
	logsMaxLines          = 500
)

// MountLogs registers GET /logs relative to the caller's prefix. It is a
// separate include (cmd proxies the one-line mount) so it can ship with the
// smallest possible surface change.
func (h *Handler) MountLogs(mux *http.ServeMux) {
	mux.HandleFunc("GET /logs", h.Svc.RequireUser(h.logs))
}

// unitCharset is the sanitize whitelist for the whole unit string: a systemd
// unit suffix plus node names stay inside [a-z0-9@._-] in practice, and any
// other byte is refused before the exec.
var unitCharset = regexp.MustCompile(`^[a-z0-9@._-]+$`)

// allowedUnit resolves the whitelisted journal unit or reports refusal.
func (h *Handler) allowedUnit(unit string) (string, bool) {
	if unit == "ovmanager" {
		return unit, true
	}
	name, ok := strings.CutPrefix(unit, "openvpn-")
	if !ok || name == "" || !unitCharset.MatchString(name) {
		return "", false
	}
	var n int
	_ = h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM nodes WHERE name = ?`, name).Scan(&n)
	if n == 0 {
		return "", false
	}
	return unit, true
}

// clampLines caps the requested tail length to [1, 500].
func clampLines(n int) int {
	if n < 1 {
		return 1
	}
	if n > logsMaxLines {
		return logsMaxLines
	}
	return n
}

func (h *Handler) logs(w http.ResponseWriter, r *http.Request) {
	unit := strings.TrimSpace(r.URL.Query().Get("unit"))
	if unit == "" {
		unit = "ovmanager"
	}
	if !unitCharset.MatchString(unit) {
		auth.WriteDetail(w, http.StatusBadRequest, logsDetailUnknownUnit)
		return
	}
	resolved, ok := h.allowedUnit(unit)
	if !ok {
		auth.WriteDetail(w, http.StatusBadRequest, logsDetailUnknownUnit)
		return
	}

	cmd := exec.Command("journalctl", "-u", resolved, "-n",
		strconv.Itoa(clampLines(intQuery(r, "lines", logsDefaultLines))), "-o", "cat", "--no-pager") //nolint:gosec // unit is whitelisted against the nodes table; the rest is static
	out, err := cmd.Output()
	if err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			stderr := string(exit.Stderr)
			// systemd runs the panel as a dedicated user; without the
			// systemd-journal group the machine journal is unreadable (the
			// unit's own user journal may still print) — name the fix.
			if strings.Contains(strings.ToLower(stderr), "permission") {
				auth.WriteDetail(w, http.StatusBadGateway, logsDetailUnreadable)
				return
			}
			auth.WriteDetail(w, http.StatusBadGateway, logsDetailFailed)
			return
		}
		auth.WriteDetail(w, http.StatusBadGateway, logsDetailMissing)
		return
	}

	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write(out)
}
