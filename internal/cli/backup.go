package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/internal/crypto"
	"github.com/anonysec/OVManager/internal/maintenance"
)

const defaultBackupKeep = 14

// coerceKeep validates --keep (1-500). Returns (keep, errorMessage).
func coerceKeep(raw string) (int, string) {
	if raw == "" {
		return 0, ""
	}
	for _, r := range raw {
		if r < '0' || r > '9' {
			return 0, fmt.Sprintf("Invalid --keep '%s' (1-500)", raw)
		}
	}
	keep, err := strconv.Atoi(raw)
	if err != nil || keep < 1 || keep > 500 {
		return 0, fmt.Sprintf("Invalid --keep '%s' (1-500)", raw)
	}
	return keep, ""
}

func runBackup(install Install, keepRaw string) (string, int) {
	keep := defaultBackupKeep
	if keepRaw != "" {
		parsed, errMsg := coerceKeep(keepRaw)
		if errMsg != "" {
			return block([]string{failedLine(errMsg)}), 1
		}
		if parsed != 0 {
			keep = parsed
		}
	}
	if info, err := os.Stat(install.InstallDir); err != nil || !info.IsDir() {
		return block([]string{failedLine("Not installed (" + install.InstallDir + " missing)")}), 1
	}
	path, err := maintenance.CreateBackup(keep, "backup", install.DataDir)
	if err != nil {
		return block([]string{failedLine("Backup failed: " + err.Error())}), 1
	}
	if path == "" {
		return block([]string{failedLine("Backup skipped because the panel database was not found")}), 1
	}
	_ = os.Chmod(path, 0o600)
	lines := []string{okLine("verified backup"), kv("path", path)}
	// A backup on the same disk is not a backup: push the newest one to the
	// configured offsite target. A failed copy is reported but not fatal —
	// the local backup is still good.
	if tool, offsiteErr := copyOffsiteAfterBackup(install.DataDir, path); offsiteErr != nil {
		lines = append(lines, failedLine("offsite copy failed: "+offsiteErr.Error()))
	} else if tool != "" {
		lines = append(lines, "copied offsite with "+tool)
	}
	return block(lines), 0
}

// runRestore lists backups, or restores one by name (cli).
func runRestore(install Install, name string) (string, int) {
	if name == "" {
		return listBackups(install)
	}
	if !filepath.IsAbs(install.InstallDir) && install.InstallDir == "" {
		return block([]string{failedLine("Not installed")}), 1
	}
	if info, err := os.Stat(install.InstallDir); err != nil || !info.IsDir() {
		return block([]string{failedLine("Not installed (" + install.InstallDir + " missing)")}), 1
	}
	if name == "" || containsSlash(name) || len(name) > 0 && name[0] == '.' {
		return block([]string{failedLine("Invalid backup name: " + name)}), 1
	}

	// Resolve the live database from effective configuration, not an assumed
	// DATA_DIR/app.db: keep OVM_APP_DIR/DATA_DIR aligned with this install
	// for the whole restore so panel helpers read the same .env.
	oldAppDir := os.Getenv("OVM_APP_DIR")
	oldDataDir := os.Getenv("DataDir")
	if install.InstallDir != "" {
		_ = os.Setenv("OVM_APP_DIR", install.InstallDir)
	}
	if install.DataDir != "" {
		_ = os.Setenv("DataDir", install.DataDir)
	}
	defer func() {
		if oldAppDir == "" {
			_ = os.Unsetenv("OVM_APP_DIR")
		} else {
			_ = os.Setenv("OVM_APP_DIR", oldAppDir)
		}
		if oldDataDir == "" {
			_ = os.Unsetenv("DataDir")
		} else {
			_ = os.Setenv("DataDir", oldDataDir)
		}
	}()

	// Encrypted backup: decrypt to a temp file first. Candidate validation
	// failures after this point are handled by the service-coordinated
	// boundary below, not by an early return.
	encrypted := strings.HasSuffix(name, ".db.enc")
	var tmpName string
	restoreName := name
	if encrypted {
		backupDir := filepath.Join(install.DataDir, "backups")
		src := filepath.Join(backupDir, name)
		if resolved, err := filepath.EvalSymlinks(src); err == nil {
			src = resolved
		}
		base, _ := filepath.Abs(backupDir)
		absSrc, _ := filepath.Abs(src)
		if !strings.HasPrefix(absSrc, base+string(os.PathSeparator)) {
			return block([]string{failedLine("Invalid backup path")}), 1
		}
		if lstat, err := os.Lstat(src); err != nil || lstat.Mode()&os.ModeSymlink != 0 {
			return block([]string{failedLine("Backup file not found: " + name)}), 1
		}
		if _, err := os.Stat(src); err != nil {
			return block([]string{failedLine("Backup file not found: " + name)}), 1
		}
		if resolved, err := filepath.EvalSymlinks(src); err == nil {
			src = resolved
		}
		key, err := crypto.GetOrCreateSecretKey(install.DataDir)
		if err != nil {
			return block([]string{failedLine("Restore failed: " + err.Error())}), 1
		}
		tmpFile, err := os.CreateTemp(backupDir, "restore-decrypted-*.db")
		if err != nil {
			return block([]string{failedLine("Restore failed: " + err.Error())}), 1
		}
		tmpName = tmpFile.Name()
		_ = tmpFile.Close()
		_ = os.Remove(tmpName)
		if err := crypto.DecryptFile(src, tmpName, key); err != nil {
			_ = os.Remove(tmpName)
			return block([]string{failedLine("Restore failed: invalid or wrong-key backup: " + err.Error())}), 1
		}
		restoreName = filepath.Base(tmpName)
	}
	cleanupTemp := func() {
		if tmpName != "" {
			_ = os.Remove(tmpName)
		}
	}

	// Reject unowned/manual service arrangements before any file action.
	if !restoreServiceOwned() {
		cleanupTemp()
		return block([]string{failedLine("Restore failed: panel service is not an owned systemd service")}), 1
	}

	wasRunning := serviceIsRunning()

	if wasRunning {
		ServiceStop(install)
		if !waitForServiceStopped() {
			cleanupTemp()
			return block([]string{failedLine("Restore failed: could not verify the service stopped")}), 1
		}
	}

	success, msg, data := maintenance.RestoreStored(restoreName, "ovmanager-cli", install.DataDir)

	resumeService := func() bool {
		if !wasRunning {
			return true
		}
		if !ServiceRestart(install) {
			return false
		}
		reachable, _ := waitHealthAny(healthURLs(install), 10, install.Cafile())
		return reachable
	}

	if !success {
		// The rollback stages its own database copy; it needs the same
		// ownership repair as a successful restore or the resumed panel
		// may find a root-owned 0600 database it cannot read.
		repairDBOwnership(restoreDBPath(install))
		resumed := resumeService()
		cleanupTemp()
		lines := []string{failedLine(msg)}
		if safety, _ := data["safety_backup"].(string); safety != "" {
			lines = append(lines, kv("Safety copy", safety))
		}
		if !resumed {
			lines = append(lines, failedLine("Service was not recovered to its previous running state"))
		}
		return block(lines), 1
	}

	// Repair ownership on the activated database.
	repairDBOwnership(restoreDBPath(install))
	repairDBOwnership(filepath.Join(install.DataDir, "secret.key"))

	if wasRunning {
		healthy := resumeService()
		cleanupTemp()
		if !healthy {
			lines := []string{failedLine("Restore succeeded but the service health check failed")}
			if safety, _ := data["safety_backup"].(string); safety != "" {
				lines = append(lines, kv("Safety copy", safety))
			}
			lines = append(lines, failedLine("Service was not recovered to a healthy state"))
			return block(lines), 1
		}
	} else {
		cleanupTemp()
	}

	items := [][2]string{{"Restored", name}}
	if safety, _ := data["safety_backup"].(string); safety != "" {
		items = append(items, [2]string{"Safety copy", safety})
	}
	if !wasRunning {
		items = append(items, [2]string{"Service", "left stopped (was not running)"})
	}
	return block(append([]string{okLine("restored")}, renderRows(items)...)), 0
}

func listBackups(install Install) (string, int) {
	backups, dir := maintenance.ListStoredBackups(install.DataDir)
	if len(backups) == 0 {
		return block([]string{heading("data backups in " + dir), hint("none — create one with: ovmanager backup")}), 1
	}
	width := 0
	for _, b := range backups {
		if len(b.Name) > width {
			width = len(b.Name)
		}
	}
	lines := []string{heading("data backups in " + dir)}
	for _, b := range backups {
		when := timeFormat(b.Mtime)
		lines = append(lines, fmt.Sprintf("  %s  %s  %s", pad(b.Name, width), when, humanSize(b.Size)))
	}
	lines = append(lines, "", hint("restore one with: ovmanager restore <name>"))
	return block(lines), 0
}

func containsSlash(s string) bool {
	for _, r := range s {
		if r == '/' || r == '\\' {
			return true
		}
	}
	return false
}
