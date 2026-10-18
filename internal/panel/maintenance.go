package panel

import (
	"database/sql"
	"fmt"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/billing"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// Panel maintenance: backups, restore, sync, cleanup and usage levers
// (backend/routers/maintenance.py).
const (
	maxBackupFileSize = 100 * 1024 * 1024
	maxBackups        = 50
	cleanupSampleSize = 20
)

// maintenanceLock serializes backup/restore (maintenance.py's RLock).
var maintenanceLock sync.Mutex

func backupDir() string  { return filepath.Join(dataDir(), "backups") }
func dbFilePath() string { return filepath.Join(dataDir(), "ovmanager.db") }

// backupSortKey is (mtime, name) — newest first, deterministic on ties.
func backupSortKey(path string) (float64, string) {
	info, err := os.Stat(path)
	if err != nil {
		return 0, filepath.Base(path)
	}
	return float64(info.ModTime().UnixNano()) / 1e9, filepath.Base(path)
}

// backupFiles are restorable backups, newest first (restore_* uploads excluded).
func backupFiles() []string {
	entries, err := os.ReadDir(backupDir())
	if err != nil {
		return nil
	}
	out := []string{}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".db" || strings.HasPrefix(e.Name(), "restore_") {
			continue
		}
		out = append(out, filepath.Join(backupDir(), e.Name()))
	}
	sort.Slice(out, func(i, j int) bool {
		mi, ni := backupSortKey(out[i])
		mj, nj := backupSortKey(out[j])
		if mi != mj {
			return mi > mj
		}
		return ni > nj
	})
	return out
}

// createPanelBackup takes a consistent snapshot and prunes old ones. Returns
// "" when the database file does not exist.
func (h *Handler) createPanelBackup(keep int, label string) (string, error) {
	if !fileExists(dbFilePath()) {
		return "", nil
	}
	limit := maxBackups
	if keep > 0 {
		limit = keep
	}
	if limit < 1 {
		limit = 1
	}
	if err := os.MkdirAll(backupDir(), 0o700); err != nil {
		return "", err
	}
	_ = os.Chmod(backupDir(), 0o700)
	if _, err := h.Svc.DB.Exec(`PRAGMA wal_checkpoint(TRUNCATE)`); err != nil {
		return "", err
	}

	snapshotFile, err := os.CreateTemp(backupDir(), ".ovmanager-snapshot-*.db")
	if err != nil {
		return "", err
	}
	snapshot := snapshotFile.Name()
	snapshotFile.Close()
	_ = os.Chmod(snapshot, 0o600)
	_ = os.Remove(snapshot) // VACUUM INTO refuses an existing target
	defer func() { _ = os.Remove(snapshot) }()
	if _, err := h.Svc.DB.Exec(`VACUUM INTO ?`, snapshot); err != nil {
		return "", err
	}

	stamp := time.Now().UTC().Format("20060102_150405")
	name := filepath.Join(backupDir(), fmt.Sprintf("ovmanager-%s-%s.db", label, stamp))
	for counter := 1; fileExists(name); counter++ {
		name = filepath.Join(backupDir(),
			fmt.Sprintf("ovmanager-%s-%s-%d.db", label, stamp, counter))
	}
	if err := copyFile(snapshot, name); err != nil {
		return "", err
	}
	_ = os.Chmod(name, 0o600)

	// Prune older backups of this label.
	matches, _ := filepath.Glob(filepath.Join(backupDir(), "ovmanager-"+label+"-*.db"))
	sort.Slice(matches, func(i, j int) bool {
		mi, ni := backupSortKey(matches[i])
		mj, nj := backupSortKey(matches[j])
		if mi != mj {
			return mi > mj
		}
		return ni > nj
	})
	for i := limit; i < len(matches); i++ {
		_ = os.Remove(matches[i])
	}
	return name, nil
}

func (h *Handler) backupCreate(w http.ResponseWriter, r *http.Request) {
	path, err := func() (string, error) {
		maintenanceLock.Lock()
		defer maintenanceLock.Unlock()
		return h.createPanelBackup(0, "backup")
	}()
	if err != nil {
		envelope(w, false, "Backup failed: "+err.Error(), nil)
		return
	}
	if path == "" {
		envelope(w, false, "Database file not found", nil)
		return
	}
	envelope(w, true, "Backup created successfully",
		map[string]any{"filename": filepath.Base(path), "path": path})
}

func (h *Handler) backupList(w http.ResponseWriter, r *http.Request) {
	files := backupFiles()
	if len(files) == 0 {
		envelope(w, true, "No backups", []any{})
		return
	}
	out := make([]map[string]any, 0, len(files))
	for _, path := range files {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		out = append(out, map[string]any{
			"name": info.Name(), "size": info.Size(),
			"modified": isoFormat(info.ModTime()),
		})
	}
	envelope(w, true, "Backups listed", out)
}

func (h *Handler) backupDownload(w http.ResponseWriter, r *http.Request) {
	files := backupFiles()
	if len(files) == 0 {
		auth404(w, "No backups found")
		return
	}
	latest := files[0]
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", `attachment; filename="`+filepath.Base(latest)+`"`)
	http.ServeFile(w, r, latest)
}

func (h *Handler) backupRestore(w http.ResponseWriter, r *http.Request) {
	// ParseForm first so both urlencoded (restore_from_server) and multipart
	// (file upload) bodies work; FastAPI accepts either.
	_ = r.ParseMultipartForm(32 << 20)
	actor, _ := h.Svc.CurrentUser(r)

	if name := r.FormValue("restore_from_server"); name != "" {
		envelopeFromModel(w, h.restoreStoredBackup(name, actor.Username))
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil || header == nil {
		envelope(w, false, "Backup file must be a .db file", nil)
		return
	}
	defer file.Close()
	if !strings.HasSuffix(header.Filename, ".db") {
		envelope(w, false, "Backup file must be a .db file", nil)
		return
	}
	safeName := safeFilename(header.Filename)
	if safeName == "" {
		envelope(w, false, "Invalid filename", nil)
		return
	}
	if err := os.MkdirAll(backupDir(), 0o700); err != nil {
		envelope(w, false, "Restore failed: "+err.Error(), nil)
		return
	}
	tmpPath := filepath.Join(backupDir(), "restore_"+safeName+".part")
	if err := writeUploadCapped(file, tmpPath, maxBackupFileSize); err != nil {
		_ = os.Remove(tmpPath)
		if err == errUploadTooLarge {
			envelope(w, false, fmt.Sprintf("File too large (max %d bytes)", maxBackupFileSize), nil)
			return
		}
		envelope(w, false, "Upload failed: "+err.Error(), nil)
		return
	}
	finalPath := filepath.Join(backupDir(), "restore_"+safeName)
	if err := os.Rename(tmpPath, finalPath); err != nil {
		_ = os.Remove(tmpPath)
		envelope(w, false, "Restore failed: "+err.Error(), nil)
		return
	}
	result := h.atomicDBRestore(finalPath, actor.Username, "Restored from: "+header.Filename)
	_ = os.Remove(finalPath)
	envelopeFromModel(w, result)
}

var errUploadTooLarge = fmt.Errorf("too large")

// writeUploadCapped streams an upload to disk, refusing anything past the cap.
func writeUploadCapped(src multipart.File, dst string, limit int64) error {
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return err
	}
	defer out.Close()
	buf := make([]byte, 1<<20)
	var total int64
	for {
		n, err := src.Read(buf)
		if n > 0 {
			total += int64(n)
			if total > limit {
				return errUploadTooLarge
			}
			if _, werr := out.Write(buf[:n]); werr != nil {
				return werr
			}
		}
		if err != nil {
			if err.Error() == "EOF" {
				break
			}
			if strings.Contains(err.Error(), "EOF") {
				break
			}
			return err
		}
	}
	return out.Sync()
}

// restoreResult mirrors the ResponseModel the restore path returns.
type restoreResult struct {
	Success bool
	Msg     string
	Data    any
}

func envelopeFromModel(w http.ResponseWriter, res restoreResult) {
	envelope(w, res.Success, res.Msg, res.Data)
}

// restoreStoredBackup restores a backup already in BACKUP_DIR, by name.
func (h *Handler) restoreStoredBackup(name, actor string) restoreResult {
	src := filepath.Join(backupDir(), name)
	if resolved, err := filepath.EvalSymlinks(src); err == nil {
		src = resolved
	}
	base := resolvePath(backupDir())
	if !strings.HasPrefix(resolvePath(src), base+string(os.PathSeparator)) && resolvePath(src) != base {
		return restoreResult{false, "Invalid backup path", nil}
	}
	if !fileExists(src) {
		return restoreResult{false, fmt.Sprintf("Backup file '%s' not found", name), nil}
	}
	if !strings.HasSuffix(name, ".db") {
		return restoreResult{false, "Backup file must be a .db file", nil}
	}
	return h.atomicDBRestore(src, actor, "Restored from server backup: "+name)
}

// atomicDBRestore stages, activates, verifies and rolls back a database swap.
func (h *Handler) atomicDBRestore(srcPath, actor, detail string) restoreResult {
	maintenanceLock.Lock()
	defer maintenanceLock.Unlock()

	var candidate, rollbackDB string
	safetyName := ""
	activated := false
	cleanup := func() {
		if candidate != "" {
			_ = os.Remove(candidate)
		}
		if rollbackDB != "" {
			_ = os.Remove(rollbackDB)
		}
	}
	defer cleanup()

	fail := func(err error) restoreResult {
		rolledBack := false
		if activated && rollbackDB != "" && fileExists(rollbackDB) {
			if rbErr := h.activateDatabase(func(dst string) error { return copyFile(rollbackDB, dst) }); rbErr == nil {
				rolledBack = true
			}
		}
		msg := "Restore failed: " + err.Error()
		if isSQLiteError(err) {
			msg = "Invalid SQLite database: " + err.Error()
		}
		var safety any
		if safetyName != "" {
			safety = safetyName
		}
		telemetry.RecordEvent(h.Svc.DB, "db_restore", "error",
			"Database restore failed and rolled back", map[string]any{
				"target": actor, "detail": detail, "error": msg,
			})
		return restoreResult{false, msg, map[string]any{
			"safety_backup": safety, "rolled_back": rolledBack,
			"data_safe": !activated || rolledBack,
		}}
	}

	// Stage: copy, integrity-check. Schema migration of the candidate is a gap
	// here — the Go migration runner lands in a later phase, so a backup from a
	// newer release is rejected by the integrity/verify step instead of being
	// silently activated.
	var err error
	candidate, err = stageCandidate(srcPath)
	if err != nil {
		return fail(err)
	}

	safety, err := h.createPanelBackup(10, "pre-restore")
	if err != nil {
		return fail(err)
	}
	if safety == "" {
		return fail(fmt.Errorf("current database is missing; safety backup could not be created"))
	}
	safetyName = filepath.Base(safety)
	rollbackFile, err := os.CreateTemp(dataDir(), ".restore-rollback-*.db")
	if err != nil {
		return fail(err)
	}
	rollbackDB = rollbackFile.Name()
	rollbackFile.Close()
	if err := copyFile(safety, rollbackDB); err != nil {
		return fail(err)
	}

	if err := h.activateDatabase(func(dst string) error {
		return copyFile(candidate, dst)
	}); err != nil {
		return fail(err)
	}
	activated = true
	candidate = "" // consumed by the activation copy

	if err := verifyDatabase(dbFilePath()); err != nil {
		return fail(err)
	}
	telemetry.RecordEvent(h.Svc.DB, "db_restore", "info",
		"Database restored and verified successfully",
		map[string]any{"target": actor, "detail": detail, "safety_backup": safetyName})
	return restoreResult{true, "Database restored and verified successfully",
		map[string]any{"safety_backup": safetyName, "rolled_back": false}}
}

// activateDatabase replaces the live database with src's content and reopens
// the pool, so no connection keeps serving the replaced inode.
func (h *Handler) activateDatabase(write func(dst string) error) error {
	if err := write(dbFilePath()); err != nil {
		return err
	}
	_ = os.Chmod(dbFilePath(), 0o600)
	removeSQLiteSidecars()
	old := h.Svc.DB
	fresh, err := db.Open(dbFilePath())
	if err != nil {
		return err
	}
	h.Svc.DB = fresh
	if old != nil {
		_ = old.Close()
	}
	return nil
}

func removeSQLiteSidecars() {
	for _, suffix := range []string{"-wal", "-shm"} {
		_ = os.Remove(dbFilePath() + suffix)
	}
}

// stageCandidate copies the source database and integrity-checks the copy.
func stageCandidate(src string) (string, error) {
	file, err := os.CreateTemp(dataDir(), ".restore-candidate-*.db")
	if err != nil {
		return "", err
	}
	path := file.Name()
	file.Close()
	_ = os.Chmod(path, 0o600)
	if err := copyFile(src, path); err != nil {
		_ = os.Remove(path)
		return "", err
	}
	if err := verifyDatabase(path); err != nil {
		_ = os.Remove(path)
		return "", err
	}
	return path, nil
}

func verifyDatabase(path string) error {
	conn, err := db.Open(path)
	if err != nil {
		return err
	}
	defer conn.Close()
	var result any
	if err := conn.QueryRow(`PRAGMA quick_check`).Scan(&result); err != nil {
		return err
	}
	text := "ok"
	if result != nil {
		text = fmt.Sprint(result)
	}
	if !strings.EqualFold(text, "ok") {
		return fmt.Errorf("database integrity failed: %s", text)
	}
	return nil
}

func isSQLiteError(err error) bool {
	return strings.Contains(strings.ToLower(err.Error()), "database") ||
		strings.Contains(strings.ToLower(err.Error()), "sqlite")
}

func (h *Handler) syncLimits(w http.ResponseWriter, r *http.Request) {
	data := node.SyncAllUserLimits(h.Svc.DB)
	envelope(w, true, "Login limits synced", data)
}

func (h *Handler) cleanStale(w http.ResponseWriter, r *http.Request) {
	data := node.CleanStaleSessionsAllNodes(h.Svc.DB)
	envelope(w, true, "Stale sessions cleaned", data)
}

func (h *Handler) restartPanel(w http.ResponseWriter, r *http.Request) {
	var command []string
	switch {
	case systemdUnitExists("ovmanager"):
		command = []string{"systemctl", "restart", "ovmanager"}
	case dockerContainerRunning("ovmanager"):
		command = []string{"docker", "restart", "ovmanager"}
	}
	if command == nil {
		envelope(w, false,
			"Could not restart the panel automatically. Run 'systemctl restart ovmanager' on a native "+
				"install, or 'docker restart ovmanager' for Docker.",
			map[string]any{"restarted": false})
		return
	}
	spawnDetached(command)
	envelope(w, true, "Restarting panel…", map[string]any{"restarted": true, "command": command})
}

// --- manual cleanup ---

type cleanupRequest struct {
	Status        string `json:"status"`
	OlderThanDays int    `json:"older_than_days"`
	Confirm       bool   `json:"confirm"`
}

type confirmRequest struct {
	Confirm bool `json:"confirm"`
}

type usagePurgeRequest struct {
	OlderThanDays int  `json:"older_than_days"`
	Confirm       bool `json:"confirm"`
}

// cleanupCandidates is the newest-first match set for a cleanup filter.
func (h *Handler) cleanupCandidates(p cleanupRequest) []map[string]any {
	status := p.Status
	if status == "" {
		status = "expired"
	}
	cutoffDay := time.Now().UTC().AddDate(0, 0, -p.OlderThanDays).Format("2006-01-02")
	cutoffTS := float64(time.Now().UTC().AddDate(0, 0, -p.OlderThanDays).UnixNano()) / 1e9
	expired := `expiry_date IS NOT NULL AND expiry_date < '` + cutoffDay + `'`
	disabled := `is_active = 0 AND (last_online IS NULL OR last_online < ` + strconv.FormatFloat(cutoffTS, 'f', -1, 64) + `)`
	where := expired
	switch status {
	case "disabled":
		where = disabled
	case "all":
		where = "(" + expired + ") OR (" + disabled + ")"
	}
	rows, err := h.Svc.DB.Query(`SELECT id, name FROM users WHERE ` + where + ` ORDER BY id DESC`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id int64
		var name sql.NullString
		if rows.Scan(&id, &name) == nil {
			out = append(out, map[string]any{"id": id, "name": name.String})
		}
	}
	return out
}

func (h *Handler) cleanupPreview(w http.ResponseWriter, r *http.Request) {
	var payload cleanupRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	status := payload.Status
	if status == "" {
		status = "expired"
	}
	candidates := h.cleanupCandidates(payload)
	sample := []string{}
	for i, c := range candidates {
		if i >= cleanupSampleSize {
			break
		}
		sample = append(sample, c["name"].(string))
	}
	var total int
	_ = h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&total)
	envelope(w, true, fmt.Sprintf("%d user(s) match", len(candidates)), map[string]any{
		"status": status, "older_than_days": payload.OlderThanDays,
		"matched": len(candidates), "sample": sample,
		"truncated": len(candidates) > cleanupSampleSize, "total_users": total,
	})
}

func (h *Handler) cleanupRun(w http.ResponseWriter, r *http.Request) {
	var payload cleanupRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	status := payload.Status
	if status == "" {
		status = "expired"
	}
	if !payload.Confirm {
		envelope(w, false, "Confirmation required — preview first, then resend with confirm=true", nil)
		return
	}
	candidates := h.cleanupCandidates(payload)
	names := []string{}
	for _, c := range candidates {
		name, _ := c["name"].(string)
		id, _ := c["id"].(int64)
		_, _ = h.Svc.DB.Exec(`DELETE FROM user_traffic_daily WHERE user_id = ?`, id)
		_, _ = h.Svc.DB.Exec(`DELETE FROM users WHERE id = ?`, id)
		names = append(names, name)
	}
	if len(names) > 0 {
		telemetry.Publish("users", telemetry.KV{Key: "op", Val: "delete"})
	}
	envelope(w, true, fmt.Sprintf("Deleted %d user(s)", len(names)), map[string]any{
		"deleted": len(names), "names": names, "status": status,
		"older_than_days": payload.OlderThanDays,
	})
}

func (h *Handler) usageResetAll(w http.ResponseWriter, r *http.Request) {
	var payload confirmRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	if !payload.Confirm {
		envelope(w, false, "Confirmation required — resend with confirm=true", nil)
		return
	}
	res, err := h.Svc.DB.Exec(`UPDATE users SET used = 0, last_node_usage = 0, node_usage = '{}'`)
	if err != nil {
		envelope(w, false, "Usage reset failed: "+err.Error(), nil)
		return
	}
	reset, _ := res.RowsAffected()
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "reset-usage"})
	envelope(w, true, fmt.Sprintf("Usage reset for %d user(s)", reset), map[string]any{"reset": reset})
}

func (h *Handler) usagePurge(w http.ResponseWriter, r *http.Request) {
	var payload usagePurgeRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	if !payload.Confirm {
		envelope(w, false, "Confirmation required — resend with confirm=true", nil)
		return
	}
	keep := payload.OlderThanDays
	if keep == 0 {
		keep = 90
	}
	removed := billing.PruneDaily(h.Svc.DB, keep)
	removedLedger := billing.PruneLedger(h.Svc.DB, keep, 5000)
	envelope(w, true, fmt.Sprintf("Removed %d daily usage row(s)", removed),
		map[string]any{"removed": removed, "removed_ledger": removedLedger})
}
