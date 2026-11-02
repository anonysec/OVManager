// `ovmanager logs` (cli): journalctl.
package cli

import (
	"os"
	"os/exec"
)

func buildLogsCommand(arg string) []string {
	if arg == "-f" {
		return []string{"journalctl", "-u", systemdService, "-n", "100", "-f"}
	}
	return []string{"journalctl", "-u", systemdService, "-n", arg, "--no-pager"}
}

func runLogs(argv []string) int {
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // command arguments are static or validated against strict allowlist
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			return exit.ExitCode()
		}
		return 1
	}
	return 0
}
