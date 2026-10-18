// Restart targets: detect how the panel is deployed (systemd unit or Docker
// container) and offer a one-click restart after a certificate change.
package panel

import (
	"net/http"
	"os/exec"
	"strings"
)

func systemdUnitExists(unit string) bool {
	systemctl, err := exec.LookPath("systemctl")
	if err != nil {
		return false
	}
	return exec.Command(systemctl, "cat", unit).Run() == nil
}

func dockerContainerRunning(name string) bool {
	docker, err := exec.LookPath("docker")
	if err != nil {
		return false
	}
	out, err := exec.Command(docker, "inspect", "--format", "{{.State.Running}}", name).Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == "true"
}

// spawnDetached runs a fixed restart command after a short delay, detached.
func spawnDetached(argv []string) {
	args := append([]string{"-c", `sleep 1; exec "$@"`, "ovmanager-restart"}, argv...)
	cmd := exec.Command("sh", args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	cmd.SysProcAttr = detachSysProcAttr()
	_ = cmd.Start()
}

func (h *Handler) tlsRestart(w http.ResponseWriter, r *http.Request) {
	var command []string
	switch {
	case systemdUnitExists("ovmanager"):
		command = []string{"systemctl", "restart", "ovmanager"}
	case dockerContainerRunning("ovmanager"):
		command = []string{"docker", "restart", "ovmanager"}
	}
	if command == nil {
		envelope(w, false,
			"Could not restart the panel automatically. Run 'systemctl restart ovmanager' on a native "+
				"install, or 'docker restart ovmanager' for Docker.",
			map[string]any{"restart_required": true, "restarted": false, "command": "systemctl restart ovmanager"})
		return
	}
	spawnDetached(command)
	envelope(w, true, "Restarting the panel now. This page will disconnect and come back in a few seconds.",
		map[string]any{"restart_required": true, "restarted": true, "command": command})
}
