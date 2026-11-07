// `ovmanager service <start|stop|restart|enable|disable>` — host-gated service
// control (manager.sh service_action). Stubs over systemctl.
package cli

import (
	"fmt"
	"io"
	"os"
	"os/exec"
)

// serviceStopImpl is the real stop; exposed as a seam so tests can record or
// simulate a stop that does not take effect.
func serviceStopImpl(install Install) {
	_ = runFix("systemctl", "stop", systemdService)
}

// serviceStartImpl is the real start.
func serviceStartImpl(install Install) {
	_ = runFix("systemctl", "start", systemdService)
}

// serviceRestartImpl is the real restart.
func serviceRestartImpl(install Install) bool {
	return runFix("systemctl", "restart", systemdService)
}

// Test seams (assigned directly by tests).
var (
	ServiceStop    = serviceStopImpl
	ServiceStart   = serviceStartImpl
	ServiceRestart = serviceRestartImpl
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
