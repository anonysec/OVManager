// CLI reuse API (Phase 5). The ovm subcommands reuse the panel's own backup,
// restore and urlpath transactions rather than re-implementing them, so there
// is exactly one implementation of each (cli/restore.py, cli/urlpath.py).
//
// These wrappers set DATA_DIR to the CLI's resolved data dir, then open the
// panel database the same way the panel does.
package panel

import (
	"os"
	"path/filepath"
	"sort"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
)

// BackupInfo is one restorable backup.
type BackupInfo struct {
	Name  string  `json:"name"`
	Size  int64   `json:"size"`
	Mtime float64 `json:"mtime"`
}

func cliHandler(dataDir string) (*Handler, func(), error) {
	_ = os.Setenv("DATA_DIR", dataDir)
	conn, err := db.Open(filepath.Join(dataDir, "ovmanager.db"))
	if err != nil {
		return nil, nil, err
	}
	return NewHandler(auth.NewService(conn, dataDir)), func() { _ = conn.Close() }, nil
}

// CreateBackup takes one panel backup (label "backup", the panel's manual
// label). Returns "" when the database file does not exist.
func CreateBackup(keep int, label, dataDir string) (string, error) {
	h, closeFn, err := cliHandler(dataDir)
	if err != nil {
		return "", err
	}
	defer closeFn()
	maintenanceLock.Lock()
	defer maintenanceLock.Unlock()
	return h.createPanelBackup(keep, label)
}

// ListStoredBackups are the restorable backups, newest first.
func ListStoredBackups(dataDir string) ([]BackupInfo, string) {
	_ = os.Setenv("DATA_DIR", dataDir)
	files := backupFiles()
	out := make([]BackupInfo, 0, len(files))
	for _, path := range files {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		out = append(out, BackupInfo{
			Name:  info.Name(),
			Size:  info.Size(),
			Mtime: float64(info.ModTime().UnixNano()) / 1e9,
		})
	}
	return out, backupDir()
}

// RestoreStored restores a backup already in the backup dir, by name, reusing
// the panel's stage/verify/activate/rollback transaction.
func RestoreStored(name, actor, dataDir string) (bool, string, map[string]any) {
	h, closeFn, err := cliHandler(dataDir)
	if err != nil {
		return false, "Restore failed: " + err.Error(), nil
	}
	defer closeFn()
	res := h.restoreStoredBackup(name, actor)
	data, _ := res.Data.(map[string]any)
	return res.Success, res.Msg, data
}

// LiveURLPath is the prefix the panel is actually serving. Returns "" when the
// database is absent (nothing has been stored yet).
func LiveURLPath(dataDir string) (string, error) {
	if !fileExists(filepath.Join(dataDir, "ovmanager.db")) {
		return "", os.ErrNotExist
	}
	h, closeFn, err := cliHandler(dataDir)
	if err != nil {
		return "", err
	}
	defer closeFn()
	return h.urlpath(), nil
}

// SetURLPath persists a new prefix, refusing the reserved ones.
func SetURLPath(value, dataDir string) (string, error) {
	h, closeFn, err := cliHandler(dataDir)
	if err != nil {
		return "", err
	}
	defer closeFn()
	return h.setURLPath(value)
}

// ReservedPrefixes lists the first path segments the panel itself owns.
func ReservedPrefixes() []string {
	out := make([]string, 0)
	for prefix := range reservedPrefixes() {
		out = append(out, prefix)
	}
	sort.Strings(out)
	return out
}
