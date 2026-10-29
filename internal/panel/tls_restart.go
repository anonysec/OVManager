// Restart targets: detect how the panel is deployed (systemd unit or Docker
// container) and offer a one-click restart after a certificate change.
package panel

import (
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
