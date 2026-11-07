// Daily database backup worker: replaces the ovmanager-backup systemd timer.
// Runs once per day inside the panel process.
package panel

import (
	"database/sql"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/backup"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

const backupWorkerBootDelay = 5 * time.Minute

var backupWorkerOnce sync.Once

func (h *Handler) startBackupWorker() {
	backupWorkerOnce.Do(func() {
		go func() {
			defer func() { recover() }()
			time.Sleep(backupWorkerBootDelay)
			ticker := time.NewTicker(time.Minute)
			defer ticker.Stop()
			runGuarded("backup worker", h.backupTick)
			for range ticker.C {
				runGuarded("backup worker", h.backupTick)
			}
		}()
	})
}

func (h *Handler) backupTick() {
	h.backupTickAt(time.Now())
}

func (h *Handler) backupTickAt(now time.Time) {
	db := h.Svc.DB()
	s := h.settings()
	if !s.boolean("auto_backup_enabled", false) {
		return
	}
	tz := s.str("timezone", "UTC")
	loc, err := time.LoadLocation(tz)
	if err != nil {
		log.Printf("backup worker: invalid timezone %q: %v", tz, err)
		return
	}
	timeStr := s.str("auto_backup_time", "03:30")
	if !autoBackupTimeRe.MatchString(timeStr) {
		log.Printf("backup worker: invalid auto backup time %q", timeStr)
		return
	}
	parts := strings.Split(timeStr, ":")
	hour, _ := strconv.Atoi(parts[0])
	minute, _ := strconv.Atoi(parts[1])

	localNow := now.In(loc)
	scheduled := time.Date(localNow.Year(), localNow.Month(), localNow.Day(), hour, minute, 0, 0, loc)
	if localNow.Before(scheduled) {
		return
	}
	day := localNow.Format("2006-01-02")

	var last string
	_ = db.QueryRow(`SELECT value FROM settings_kv WHERE key = ?`, "backup.last_success_day").Scan(&last)
	if last == day {
		return
	}

	keep := orDefault(s.num("auto_backup_keep", 50), 50)
	if keep < autoBackupKeepMin {
		keep = autoBackupKeepMin
	}

	maintenanceLock.Lock()
	path, err := h.createPanelBackup(keep, "auto")
	maintenanceLock.Unlock()
	if err != nil {
		log.Printf("backup worker: %v", err)
		return
	}
	if path == "" {
		return
	}
	if err := verifyDatabase(path); err != nil {
		_ = os.Remove(path)
		log.Printf("backup worker: snapshot verification failed: %v", err)
		return
	}

	target := strings.TrimSpace(s.strOr("offsite_backup_target"))
	if target != "" {
		tool, copyErr := backup.CopyOffsite(dataDir(), path, target)
		recordOffsiteResult(db, target, tool, copyErr)
		if copyErr != nil {
			// Local success is not offsite success: leave the success day
			// unset so the next tick retries the copy.
			log.Printf("backup worker: offsite copy failed: %v", copyErr)
			return
		}
	}

	_, _ = db.Exec(
		`INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?`,
		"backup.last_success_day", day, now.Unix(),
		day, now.Unix(),
	)
	log.Printf("backup worker: created %s", path)
}

func recordOffsiteResult(db *sql.DB, target, tool string, copyErr error) {
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
	telemetry.RecordEvent(db, "backup_offsite", severity, message, meta)
}
