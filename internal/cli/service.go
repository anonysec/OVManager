// `ovmanager service <start|stop|restart|enable|disable>` — host-gated service
// control (manager.sh service_action). Stubs over systemctl.
package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
)

func runServiceAction(install Install, action string, out io.Writer) int {
	argv := []string{"systemctl", action, systemdService}
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // command arguments are static or validated against strict allowlist
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		fmt.Fprintln(out, failedLine("Failed: "+fmt.Sprint(argv)))
		return 1
	}
	return 0
}
