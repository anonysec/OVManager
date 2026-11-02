// Telegram worker wiring (plan Task 4): the notify package's single worker
// goroutine is started from Panel Mount — the same site as the ACME renewal
// worker — with the daily-backup attachment supplied from this package. The
// snapshot for the summary attachment is created through the same
// transactional VACUUM INTO helper the maintenance backup routes use, so a
// backup taken for Telegram counts toward the same prune limits.
package panel

import (
	"database/sql"
	"log"
	"os"
	"path/filepath"

	"github.com/anonysec/OVManager/go/internal/notify"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	_ "modernc.org/sqlite"
)

// telegramAttachLimit is the size ceiling for the summary backup attachment.
const telegramAttachLimit = notify.MaxDocumentBytes

// startTelegramWorker launches the notify loop once per process. Idempotent,
// so Mount can call it unconditionally.
func (h *Handler) startTelegramWorker() {
	notify.StartWorker(h.Svc.DB(), h.telegramBackupPayload, telemetry.CollectMetrics)
}

func sanitizeTelegramBackup(srcPath string) (string, error) {
	tmpDir := filepath.Dir(srcPath)
	sanitizedPath := filepath.Join(tmpDir, "sanitized-"+filepath.Base(srcPath))
	data, err := os.ReadFile(srcPath) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(sanitizedPath, data, 0o600); err != nil {
		return "", err
	}
	db, err := sql.Open("sqlite", sanitizedPath)
	if err != nil {
		_ = os.Remove(sanitizedPath)
		return "", err
	}
	defer db.Close()

	// Redact active sessions, telegram bot token, and node API keys
	_, _ = db.Exec("DELETE FROM sessions;")
	_, _ = db.Exec("UPDATE settings SET bot_token = '' WHERE bot_token IS NOT NULL;")
	_, _ = db.Exec("UPDATE nodes SET key = '[REDACTED]';")
	_, _ = db.Exec("VACUUM;")
	_ = db.Close()

	return sanitizedPath, nil
}

// telegramBackupPayload produces the daily backup attachment when the
// telegram_backup_enabled switch is on. Any failure is silent — the summary
// text still goes out (notifications fail open).
func (h *Handler) telegramBackupPayload() (string, []byte) {
	if !h.settings().boolean("telegram_backup_enabled", false) {
		return "", nil
	}
	maintenanceLock.Lock()
	path, err := h.createPanelBackup(0, "backup")
	maintenanceLock.Unlock()
	if err != nil || path == "" {
		if err != nil {
			log.Printf("telegram: backup snapshot failed: %v", err)
		}
		return "", nil
	}
	sanitizedPath, err := sanitizeTelegramBackup(path)
	if err != nil {
		log.Printf("telegram: backup sanitization failed: %v", err)
		return "", nil
	}
	defer os.Remove(sanitizedPath)

	info, err := os.Stat(sanitizedPath)
	if err == nil && info.Size() > telegramAttachLimit {
		log.Printf("telegram: backup %s is %d bytes, over the attach cap", sanitizedPath, info.Size())
		return "", nil
	}
	data, err := os.ReadFile(sanitizedPath) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return "", nil
	}
	return filepath.Base(path), data
}
