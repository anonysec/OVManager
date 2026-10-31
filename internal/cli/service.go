// `ovm service <start|stop|restart|enable|disable>` — host-gated service
// control (manager.sh service_action). Stubs over systemctl/docker.
package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
)

func runServiceAction(install Install, action string, out io.Writer) int {
	var argv []string
	if fileExists(install.ComposeFile()) {
		switch action {
		case "start":
			argv = []string{"docker", "start", "ovmanager"}
		case "stop":
			argv = []string{"docker", "stop", "ovmanager"}
		case "restart":
			argv = []string{"docker", "restart", "-t", "10", "ovmanager"}
		case "enable":
			argv = []string{"docker", "update", "--restart", "unless-stopped", "ovmanager"}
		case "disable":
			argv = []string{"docker", "update", "--restart", "no", "ovmanager"}
		}
	} else {
		argv = []string{"systemctl", action, systemdService}
	}
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // triaged intentional
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Fprintln(out, failedLine("Failed: "+fmt.Sprint(argv)))
		return 1
	}
	return 0
}
