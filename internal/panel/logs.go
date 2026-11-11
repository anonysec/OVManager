// GET /logs — journal tail for the panel unit.
//
// Only the panel's own unit is readable. Nodes run on other hosts; a local
// journal cannot show their logs, and the old openvpn-<name> whitelist
// pointed at units that no longer exist.
package panel

import (
	"net/http"
	"os/exec"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/internal/auth"
)

const (
	logsDetailUnknownUnit = "Unknown unit (allowed: ovmanager)"
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
	if unit != "ovmanager" {
		auth.WriteDetail(w, http.StatusBadRequest, logsDetailUnknownUnit)
		return
	}

	cmd := exec.Command("journalctl", "-u", unit, "-n", // #nosec // unit is a single constant; the rest is static
		strconv.Itoa(clampLines(intQuery(r, "lines", logsDefaultLines))), "-o", "cat", "--no-pager")
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
	_, _ = w.Write(out) // #nosec // journal output served as text/plain // #nosec // journal output served as text/plain
}
