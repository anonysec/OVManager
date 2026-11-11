// Daily database backup worker: replaces the ovmanager-backup systemd timer.
// Runs once per day inside the panel process.
package panel

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/backup"
	"github.com/anonysec/OVManager/internal/crypto"
	"github.com/anonysec/OVManager/internal/node"
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

	// Node backups: each node owns its PKI, so the panel keeps a copy of the
	// archive next to its own database backup.
	h.backupNodes(path, keep)

	// Optional encryption at rest, using the panel secret key.
	if s.boolean("backup_encrypt_enabled", false) {
		key, keyErr := crypto.GetOrCreateSecretKey(dataDir())
		if keyErr != nil {
			log.Printf("backup worker: encryption key unavailable: %v", keyErr)
			return
		}
		encPath := path + ".enc"
		if err := crypto.EncryptFile(path, encPath, key); err != nil {
			log.Printf("backup worker: encryption failed: %v", err)
			return
		}
		_ = os.Remove(path)
		path = encPath
	}

	target := strings.TrimSpace(s.strOr("offsite_backup_target"))
	if target != "" {
		tool, copyErr := backup.CopyOffsite(dataDir(), path, target)
		recordOffsiteResult(db, target, tool, copyErr)
		if copyErr != nil {
			log.Printf("backup worker: offsite copy failed: %v", copyErr)
			return
		}
	}

	// Telegram backup (optional): send the snapshot to the owner chat.
	if s.boolean("telegram_backup_enabled", false) {
		token := s.strOr("bot_token")
		var chatID int64
		_ = db.QueryRow(`SELECT COALESCE(owner_telegram_id,0) FROM Setting LIMIT 1`).Scan(&chatID)
		if token != "" && chatID != 0 {
			data, err := os.ReadFile(path) // #nosec G304 // path is the panel-generated backup snapshot
			if err == nil {
				name := filepath.Base(path)
				if !telemetry.TgSendDocumentExported(token, chatID, name, data, "OVManager backup "+day) {
					log.Printf("backup worker: telegram upload failed")
					return
				}
			}
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

// readSetting reads the backup_last_success_day column from settings.
func readSetting(db *sql.DB, key string) string {
	var v sql.NullString
	_ = db.QueryRow(`SELECT backup_last_success_day FROM Setting ORDER BY id LIMIT 1`).Scan(&v)
	if v.Valid {
		return v.String
	}
	return ""
}

// writeSetting persists backup_last_success_day into settings.
func writeSetting(db *sql.DB, key, value string, nowUnix int64) error {
	_, err := db.Exec(`UPDATE Setting SET backup_last_success_day = ? WHERE id = (SELECT MIN(id) FROM Setting)`, value)
	return err
}

// backupNodes pulls each active node's backup archive into the backup
// directory. A node that is unreachable or answers without an archive is
// skipped: the panel's own backup is still valid without it.
func (h *Handler) backupNodes(panelBackupPath string, keep int) {
	nodes := node.GetActiveNodes(h.Svc.DB())
	if len(nodes) == 0 {
		return
	}
	dir := backupDir()
	stamp := time.Now().UTC().Format("20060102_150405")
	for _, n := range nodes {
		pid := node.PanelIDFor(h.Svc.DB())
		c := node.NodeClient(n, pid)
		name := fmt.Sprintf("ovnode-node%d-%s.tar.gz", n.ID, stamp)
		dest := filepath.Join(dir, name)
		written, err := c.DownloadBackup(dest, 120*time.Second)
		if err != nil {
			log.Printf("backup worker: node %s backup failed: %v", n.Name, err)
			continue
		}
		log.Printf("backup worker: stored node %s backup (%d bytes)", n.Name, written)
	}
	// Prune old node archives of the same label.
	matches, _ := filepath.Glob(filepath.Join(dir, "ovnode-node*-*.tar.gz"))
	sort.Slice(matches, func(i, j int) bool { return matches[i] > matches[j] })
	limit := keep
	if limit < 1 {
		limit = 50
	}
	for i := limit; i < len(matches); i++ {
		_ = os.Remove(matches[i])
	}
}
