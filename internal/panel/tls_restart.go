// Restart targets: detect the systemd unit and offer a one-click restart
// after a certificate change.
package panel

import (
	"os/exec"
)

func systemdUnitExists(unit string) bool {
	systemctl, err := exec.LookPath("systemctl")
	if err != nil {
		return false
	}
	return exec.Command(systemctl, "cat", unit).Run() == nil // #nosec G204 // command arguments are static or validated against strict allowlist
}

// spawnDetached runs a fixed restart command after a short delay, detached.
func spawnDetached(argv []string) {
	args := append([]string{"-c", `sleep 1; exec "$@"`, "ovmanager-restart"}, argv...)
	cmd := exec.Command("sh", args...) // #nosec G204 // command arguments are static or validated against strict allowlist
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	cmd.SysProcAttr = detachSysProcAttr()
	_ = cmd.Start()
}
