// `ovm backup` (cli/backup.py backup_now + manager.sh backup_now).
package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"ovmanager-go/internal/panel"
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
	path, err := panel.CreateBackup(keep, "backup", install.DataDir)
	if err != nil {
		return block([]string{failedLine("Backup failed: " + err.Error())}), 1
	}
	if path == "" {
		return block([]string{failedLine("Backup skipped because the panel database was not found")}), 1
	}
	_ = os.Chmod(path, 0o600)
	return block([]string{okLine("verified backup"), kv("path", path)}), 0
}

// runRestore lists backups, or restores one by name (cli/restore.py).
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
	success, msg, data := panel.RestoreStored(name, "ovm-cli", install.DataDir)
	if !success {
		lines := []string{failedLine(msg)}
		if safety, _ := data["safety_backup"].(string); safety != "" {
			lines = append(lines, kv("Safety copy", safety))
		}
		return block(lines), 1
	}
	items := [][2]string{{"Restored", name}}
	if safety, _ := data["safety_backup"].(string); safety != "" {
		items = append(items, [2]string{"Safety copy", safety})
	}
	return block(append([]string{okLine("restored")}, renderRows(items)...)), 0
}

func listBackups(install Install) (string, int) {
	backups, dir := panel.ListStoredBackups(install.DataDir)
	if len(backups) == 0 {
		return block([]string{heading("data backups in " + dir), hint("none — create one with: ovm backup")}), 1
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
	lines = append(lines, "", hint("restore one with: ovm restore <name>"))
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
