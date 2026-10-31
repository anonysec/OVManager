// `ovmanager logs` (cli): docker logs or journalctl, same selection rules.
package cli

import (
	"os"
	"os/exec"
)

func buildLogsCommand(composeFile, arg string) []string {
	if fileExists(composeFile) {
		if arg == "-f" {
			return []string{"docker", "logs", "-f", "--tail", "100", "ovmanager"}
		}
		return []string{"docker", "logs", "--tail", arg, "ovmanager"}
	}
	if arg == "-f" {
		return []string{"journalctl", "-u", systemdService, "-n", "100", "-f"}
	}
	return []string{"journalctl", "-u", systemdService, "-n", arg, "--no-pager"}
}

func runLogs(argv []string) int {
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // triaged intentional
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			return exit.ExitCode()
		}
		return 1
	}
	return 0
}
