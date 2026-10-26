// The offsite backup copy.
//
// A backup on the same disk is not a backup. The scheduled backup (the
// installer's daily timer) can push the newest backup to another machine
// over SSH.
//
// The target is [user@]host:/absolute/path, validated by the maintenance. The
// transfer uses key-based login in BatchMode, so it can never wait for a
// password prompt: it either copies the file or fails. Nothing else on the
// remote side is created, rotated or cleaned up — retention there belongs to
// the operator. The outcome is written to the audit log.
package cli

import (
	"fmt"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/maintenance"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// offsiteCopy pushes one backup file to the offsite target. It returns the
// tool it used ("rsync" or "scp") and the error, if any.
func offsiteCopy(target, path string) (string, error) {
	user, host, dir, err := maintenance.ParseOffsiteTarget(target)
	if err != nil {
		return "", err
	}
	dest := host
	if user != "" {
		dest = user + "@" + host
	}
	remote := dest + ":" + strings.TrimSuffix(dir, "/") + "/" + filepath.Base(path)

	// The destination is the only user input and the parser restricts it to
	// a safe character set; -e is a constant, so nothing user-supplied
	// reaches a shell.
	if _, lookErr := exec.LookPath("rsync"); lookErr == nil {
		cmd := exec.Command("rsync", "-a", "-e", "ssh -o BatchMode=yes", path, remote)
		if out, runErr := cmd.CombinedOutput(); runErr != nil {
			return "rsync", fmt.Errorf("rsync failed: %s", strings.TrimSpace(string(out)))
		}
		return "rsync", nil
	}
	cmd := exec.Command("scp", "-o", "BatchMode=yes", path, remote)
	if out, runErr := cmd.CombinedOutput(); runErr != nil {
		return "scp", fmt.Errorf("scp failed: %s", strings.TrimSpace(string(out)))
	}
	return "scp", nil
}

// copyOffsiteAfterBackup copies the newest backup to the configured target
// and records the outcome in the audit log. A missing target is not an error
// (offsite copies are optional); a failed copy is reported, not fatal — the
// local backup is still good.
func copyOffsiteAfterBackup(dataDir, path string) (string, error) {
	target, err := maintenance.OffsiteBackupTarget(dataDir)
	if err != nil {
		return "", err
	}
	target = strings.TrimSpace(target)
	if target == "" {
		return "", nil
	}
	tool, copyErr := offsiteCopy(target, path)
	recordOffsiteCopy(dataDir, target, tool, copyErr)
	if copyErr != nil {
		return tool, copyErr
	}
	return tool, nil
}

// recordOffsiteCopy writes the outcome to the audit log: a copy is a
// security-relevant event, and the operator needs to see that it happened (or
// that it did not).
func recordOffsiteCopy(dataDir, target, tool string, copyErr error) {
	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		return
	}
	defer func() { _ = conn.Close() }()

	severity := "info"
	message := "Offsite backup copied."
	detail := ""
	if copyErr != nil {
		severity = "error"
		message = "Offsite backup copy failed."
		detail = copyErr.Error()
	}
	meta := map[string]any{"target": target, "tool": tool}
	if detail != "" {
		meta["detail"] = detail
	}
	telemetry.RecordEvent(conn, "backup_offsite", severity, message, meta)
}
