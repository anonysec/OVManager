// Daily database backup worker: replaces the ovmanager-backup systemd timer.
// Runs once per day inside the panel process.
package panel

import (
	"context"
	"database/sql"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/backup"
	"github.com/anonysec/OVManager/internal/telemetry"
)

const backupWorkerBootDelay = 5 * time.Minute

var backupWorkerOnce sync.Once

func (h *Handler) startBackupWorker() {
	backupWorkerOnce.Do(func() {
		Run(context.Background(), []job{{
			name:  "backup worker",
			delay: backupWorkerBootDelay,
			every: func() time.Duration { return time.Minute },
			fn:    func(ctx context.Context) { h.backupTick(ctx) },
		}})
	})
}

func (h *Handler) backupTick(ctx context.Context) {
	select {
	case <-ctx.Done():
		return
	default:
	}
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

	last := readSetting(db, settingKeyBackupLastSuccessDay)
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

	_ = writeSetting(db, settingKeyBackupLastSuccessDay, day, now.Unix())
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

// settingKeyBackupLastSuccessDay is the settings_kv key read/written below.
const settingKeyBackupLastSuccessDay = "backup.last_success_day"

// readSetting reads one settings_kv row without failing the tick.
func readSetting(db *sql.DB, key string) string {
	var v string
	_ = db.QueryRow(`SELECT value FROM settings_kv WHERE key = ?`, key).Scan(&v)
	return v
}

// writeSetting persists one settings_kv row atomically.
func writeSetting(db *sql.DB, key, value string, nowUnix int64) error {
	_, err := db.Exec(
		`INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, ?)
		 ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?`,
		key, value, nowUnix, value, nowUnix)
	return err
}
