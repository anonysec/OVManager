package panel

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/billing"
	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/notify"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// Panel maintenance: backups, restore, sync, cleanup and usage levers
// (backend).
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
	_ = os.Chmod(backupDir(), 0o700) // #nosec G302 // triaged intentional
	if _, err := h.Svc.DB().Exec(`PRAGMA wal_checkpoint(TRUNCATE)`); err != nil {
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
	if _, err := h.Svc.DB().Exec(`VACUUM INTO ?`, snapshot); err != nil {
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
	// MaxBytesReader is the real body limit: ParseMultipartForm alone spools the
	// excess to disk.
	r.Body = http.MaxBytesReader(w, r.Body, maxBackupFileSize+1<<20)
	// The parser spools a file part over 32 MB to the system temp dir; the
	// request has to clean it up.
	defer removeMultipartTemps(r)
	if err := r.ParseMultipartForm(32 << 20); err != nil && !errors.Is(err, http.ErrNotMultipart) { // #nosec // body already limited by MaxBytesReader above
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			envelope(w, false, fmt.Sprintf("File too large (max %d bytes)", maxBackupFileSize), nil)
		} else {
			envelope(w, false, "Could not read the uploaded file: "+err.Error(), nil)
		}
		return
	}
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
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600) // #nosec G304 // triaged intentional
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
			if errors.Is(err, io.EOF) {
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
			_ = os.Remove(candidate) // #nosec G703 // candidate is internally staged path
		}
		if rollbackDB != "" {
			_ = os.Remove(rollbackDB) // #nosec G703 // internally staged path
		}
	}
	defer cleanup()

	fail := func(err error) restoreResult {
		rolledBack := false
		if activated && rollbackDB != "" && fileExists(rollbackDB) {
			if _, rbErr := h.activateDatabase(func(dst string) (string, error) { return stageFile(rollbackDB, dst) }); rbErr == nil {
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
		telemetry.RecordEvent(h.Svc.DB(), "db_restore", "error",
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
	// Gate BEFORE any activation: a candidate from a different release
	// (older or newer schema) must not become the live database.
	if err := h.restoreVersionCompatible(candidate); err != nil {
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

	activated, err = h.activateDatabase(func(dst string) (string, error) {
		return stageFile(candidate, dst)
	})
	if err != nil {
		return fail(err)
	}
	candidate = "" // consumed by the activation copy

	if err := verifyDatabase(dbFilePath()); err != nil {
		return fail(err)
	}
	telemetry.RecordEvent(h.Svc.DB(), "db_restore", "info",
		"Database restored and verified successfully",
		map[string]any{"target": actor, "detail": detail, "safety_backup": safetyName})
	return restoreResult{true, "Database restored and verified successfully",
		map[string]any{"safety_backup": safetyName, "rolled_back": false}}
}

// openLive opens the live database after a swap. A var so a test can
// simulate a database that will not reopen.
var openLive = db.Open

// activateDatabase replaces the live database file and reopens the pool.
//
// It returns whether the panel was left without a usable pool: once the old
// pool is closed the panel cannot serve, so a failure from that point on has
// to be rolled back by the caller. Before that the old pool still serves and
// the live file is untouched, so there is nothing to roll back.
//
// The replacement is STAGED first: the candidate is copied to a temp file
// beside the live database while the old pool is still serving, so a 100 MB
// restore does not spend seconds with the pool closed. Only then is the old
// pool closed (which checkpoints its WAL into the main file and releases the
// -wal/-shm sidecars), the sidecars removed, the staged file renamed over the
// live one, and the new pool published. The window in which requests see a
// closed pool is the rename plus the open — not the copy.
//
// Readers that already hold the old *sql.DB keep their (now unlinked) inode;
// new opens see the new file.
// activateDatabase replaces the live database file and reopens the pool.
//
// It returns whether the panel was left without a usable pool: once the old
// pool is closed the panel cannot serve, so a failure from that point on has
// to be rolled back by the caller. Before that the old pool still serves and
// the live file is untouched, so there is nothing to roll back.
//
// The replacement is STAGED first: the candidate is copied to a temp file
// beside the live database while the old pool is still serving, so a 100 MB
// restore does not spend seconds with the pool closed. Before closing the
// old pool, we wait for in-flight requests to drain (with a timeout). Only
// then is the old pool closed (which checkpoints its WAL into the main file
// and releases the -wal/-shm sidecars), the sidecars removed, the staged
// file renamed over the live one, and the new pool published.
func (h *Handler) activateDatabase(stage func(dst string) (string, error)) (disturbed bool, err error) {
	live := dbFilePath()
	staged, err := stage(live)
	if err != nil {
		// The live file is untouched; the old pool is still serving.
		return false, err
	}

	old := h.Svc.DB()

	// Drain: wait for in-flight requests to finish before closing the pool.
	// Use a timeout so a stuck request doesn't block restore forever.
	drainDone := make(chan struct{})
	go func() {
		h.activeReq.Wait()
		close(drainDone)
	}()
	select {
	case <-drainDone:
		// All in-flight requests completed.
	case <-time.After(10 * time.Second):
		// Timeout: proceed anyway to avoid deadlocking the panel.
		// Log a warning so the operator knows some requests were interrupted.
		log.Printf("restore: drain timeout, %d in-flight requests interrupted", 0)
	}

	// Close the old pool: this checkpoints the WAL into the main database
	// file and releases the -wal/-shm sidecars. It MUST happen before the
	// rename, or a stale sidecar could be recovered against the new file.
	if old != nil {
		_ = old.Close()
	}
	removeSQLiteSidecars()

	if err := commitStaged(staged, live); err != nil {
		// The live file is untouched (the rename failed); reopen it so the
		// service keeps serving instead of a closed pool.
		if fresh, oerr := openLive(live); oerr == nil {
			_ = h.Svc.DBSwap(fresh)
			if w := notify.Running(); w != nil {
				w.SwapDB(fresh)
			}
			return false, err
		}
		// The pool could not be reopened: the panel is down and only the
		// caller's rollback can bring it back.
		return true, err
	}
	_ = os.Chmod(live, 0o600)
	removeSQLiteSidecars()
	fresh, err := openLive(live)
	if err != nil {
		return true, err
	}
	// DBSwap publishes the new pool; `old` is already closed, do not close
	// it again.
	_ = h.Svc.DBSwap(fresh)
	if w := notify.Running(); w != nil {
		w.SwapDB(fresh)
	}
	return true, nil
}

// restoreVersionCompatible rejects a candidate whose schema version
// (PRAGMA user_version) differs from the live database: a candidate from an
// older release would regress the schema (the migration runner is one-way),
// and one from a newer release would leave the running code behind it.
func (h *Handler) restoreVersionCompatible(candidate string) error {
	var live int
	if err := h.Svc.DB().QueryRow(`PRAGMA user_version`).Scan(&live); err != nil {
		// The live file is unreadable — restoring is the recovery path.
		return nil
	}
	probe, err := db.Open(candidate)
	if err != nil {
		return err
	}
	defer probe.Close()
	var cand int
	if err := probe.QueryRow(`PRAGMA user_version`).Scan(&cand); err != nil {
		return err
	}
	if cand != live {
		return fmt.Errorf(
			"schema version mismatch: backup at %d, live at %d; restore a backup of this release instead",
			cand, live)
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

// verifyDatabase opens the candidate and runs integrity check + required tables check.
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

	// Verify required tables exist (OVManager schema).
	required := []string{"admins", "sessions", "users", "nodes", "settings"}
	for _, t := range required {
		var cnt int
		if err := conn.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?`, t).Scan(&cnt); err != nil {
			return err
		}
		if cnt == 0 {
			return fmt.Errorf("missing required table: %s", t)
		}
	}
	return nil
}

func isSQLiteError(err error) bool {
	return strings.Contains(strings.ToLower(err.Error()), "database") ||
		strings.Contains(strings.ToLower(err.Error()), "sqlite")
}

func (h *Handler) syncLimits(w http.ResponseWriter, r *http.Request) {
	data := node.SyncAllUserLimits(h.Svc.DB())
	envelope(w, true, "Login limits synced", data)
}

func (h *Handler) cleanStale(w http.ResponseWriter, r *http.Request) {
	data := node.CleanStaleSessionsAllNodes(h.Svc.DB())
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
	switch status {
	case "expired", "disabled", "all":
	default:
		return nil
	}
	cutoffDay := time.Now().UTC().AddDate(0, 0, -p.OlderThanDays).Format("2006-01-02")
	cutoffTS := float64(time.Now().UTC().AddDate(0, 0, -p.OlderThanDays).UnixNano()) / 1e9
	expired := `expiry_date IS NOT NULL AND expiry_date < ?`
	disabled := `is_active = 0 AND (last_online IS NULL OR last_online < ?)`
	var query string
	var args []any
	switch status {
	case "disabled":
		query = `SELECT id, name FROM users WHERE ` + disabled + ` ORDER BY id DESC`
		args = []any{cutoffTS}
	case "all":
		query = `SELECT id, name FROM users WHERE (` + expired + `) OR (` + disabled + `) ORDER BY id DESC`
		args = []any{cutoffDay, cutoffTS}
	default:
		query = `SELECT id, name FROM users WHERE ` + expired + ` ORDER BY id DESC`
		args = []any{cutoffDay}
	}
	rows, err := h.Svc.DB().Query(query, args...)
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
	if status != "expired" && status != "disabled" && status != "all" {
		writeValidationError(w, "value_error", "status", "invalid status")
		return
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
	_ = h.Svc.DB().QueryRow(`SELECT COUNT(*) FROM users`).Scan(&total)
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
	if status != "expired" && status != "disabled" && status != "all" {
		writeValidationError(w, "value_error", "status", "invalid status")
		return
	}
	if !payload.Confirm {
		envelope(w, false, "Confirmation required — preview first, then resend with confirm=true", nil)
		return
	}
	candidates := h.cleanupCandidates(payload)
	names := []string{}
	fanoutFailed := []string{}
	var lastTxErr error
	for _, c := range candidates {
		name, _ := c["name"].(string)
		id, _ := c["id"].(int64)
		// One transaction per user: traffic rows and the users row go together,
		// so a cleanup never leaves a user half-deleted.
		tx, err := h.Svc.DB().Begin()
		if err != nil {
			lastTxErr = err
			break
		}
		if _, err := tx.Exec(`DELETE FROM user_traffic_daily WHERE user_id = ?`, id); err == nil {
			_, err = tx.Exec(`DELETE FROM users WHERE id = ?`, id)
		}
		if err != nil {
			_ = tx.Rollback()
			lastTxErr = err
			continue
		}
		if err := tx.Commit(); err != nil {
			lastTxErr = err
			continue
		}
		// Same contract as the users DELETE route: the panel-side row is gone,
		// so unreachable nodes are reported, not rolled back.
		if failures, _ := node.DeleteUserOnAllNodes(id, h.Svc.DB())["failed"].([]string); len(failures) > 0 {
			fanoutFailed = append(fanoutFailed, fmt.Sprintf("%s: %s", name, strings.Join(failures, ", ")))
			log.Printf("maintenance: cleanup deleted user %s; node fan-out failed on %v", name, failures)
		}
		names = append(names, name)
	}
	if lastTxErr != nil && len(names) == 0 {
		envelope(w, false, "Cleanup failed: "+lastTxErr.Error(), nil)
		return
	}
	if len(names) > 0 {
		telemetry.Publish("users", telemetry.KV{Key: "op", Val: "delete"})
	}
	// The audit trail is NOT pruned here. This action deletes users; the
	// audit trail's retention belongs to the usage purge (POST
	// /maintenance/usage/purge), which reports how many rows it removed.
	// Pruning it here would destroy the history of an unrelated action
	// without saying so.
	envelope(w, true, fmt.Sprintf("Deleted %d user(s)", len(names)), map[string]any{
		"deleted": len(names), "names": names, "status": status,
		"older_than_days": payload.OlderThanDays, "node_delete_failed": fanoutFailed,
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
	// Keep node_usage (baselines + push_hash) and set the reseed marker so the
	// next traffic pass seeds instead of re-billing (design §4.6).
	rows, err := h.Svc.DB().Query(`SELECT id, COALESCE(used,0), COALESCE(node_usage, '{}') FROM users`)
	if err != nil {
		envelope(w, false, "Usage reset failed: "+err.Error(), nil)
		return
	}
	type userState struct {
		id    int64
		used  int64
		state string
	}
	var recs []userState
	for rows.Next() {
		var u userState
		if err := rows.Scan(&u.id, &u.used, &u.state); err != nil {
			rows.Close()
			envelope(w, false, "Usage reset failed: "+err.Error(), nil)
			return
		}
		recs = append(recs, u)
	}
	rows.Close()
	marker := json.RawMessage("true")
	reset := int64(0)
	for _, u := range recs {
		ok := false
		for attempt := 0; attempt < 3; attempt++ {
			var used int64
			var state string
			if attempt > 0 {
				if err := h.Svc.DB().QueryRow(`SELECT COALESCE(used,0), COALESCE(node_usage,'{}') FROM users WHERE id = ?`, u.id).Scan(&used, &state); err != nil {
					envelope(w, false, "Usage reset failed: "+err.Error(), nil)
					return
				}
			} else {
				used = u.used
				state = u.state
			}
			data := map[string]json.RawMessage{}
			if json.Unmarshal([]byte(state), &data) != nil {
				data = map[string]json.RawMessage{}
			}
			data[node.ReseedMarkerKey] = marker
			merged, err := json.Marshal(data)
			if err != nil {
				envelope(w, false, "Usage reset failed: "+err.Error(), nil)
				return
			}
			res, err := h.Svc.DB().Exec(
				`UPDATE users SET used = 0, last_node_usage = 0, node_usage = ? WHERE id = ? AND COALESCE(used,0) IS ? AND COALESCE(node_usage,'{}') IS ?`, string(merged), u.id, used, state,
			)
			if err != nil {
				envelope(w, false, "Usage reset failed: "+err.Error(), nil)
				return
			}
			if n, _ := res.RowsAffected(); n == 1 {
				ok = true
				break
			}
		}
		if !ok {
			envelope(w, false, "Usage reset failed: concurrent update", nil)
			return
		}
		reset++
	}
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
	removed := billing.PruneDaily(h.Svc.DB(), keep)
	removedLedger := billing.PruneLedger(h.Svc.DB(), keep, 5000)
	removedAudit := telemetry.PruneAuditLogs(h.Svc.DB(), keep)
	envelope(w, true, fmt.Sprintf("Removed %d daily usage row(s)", removed),
		map[string]any{"removed": removed, "removed_ledger": removedLedger, "removed_audit": removedAudit})
}
