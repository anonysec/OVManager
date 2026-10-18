// Telegram worker wiring (plan Task 4): the notify package's single worker
// goroutine is started from Panel Mount — the same site as the ACME renewal
// worker — with the daily-backup attachment supplied from this package. The
// snapshot for the summary attachment is created through the same
// transactional VACUUM INTO helper the maintenance backup routes use, so a
// backup taken for Telegram counts toward the same prune limits.
package panel

import (
	"log"
	"os"
	"path/filepath"

	"github.com/anonysec/OVManager/go/internal/notify"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// telegramAttachLimit is the size ceiling for the summary backup attachment.
const telegramAttachLimit = notify.MaxDocumentBytes

// startTelegramWorker launches the notify loop once per process. Idempotent,
// so Mount can call it unconditionally.
func (h *Handler) startTelegramWorker() {
	notify.StartWorker(h.Svc.DB(), h.telegramBackupPayload, telemetry.CollectMetrics)
}

// telegramBackupPayload produces the daily backup attachment when the
// telegram_backup_enabled switch is on. Any failure is silent — the summary
// text still goes out (notifications fail open).
//
// ponytail: taking a fresh snapshot per summary costs one VACUUM INTO a day;
// reading the newest existing backup would race the prune, add a flag if
// snapshot cost ever matters.
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
	info, err := os.Stat(path)
	if err == nil && info.Size() > telegramAttachLimit {
		log.Printf("telegram: backup %s is %d bytes, over the attach cap", path, info.Size())
		return "", nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", nil
	}
	return filepath.Base(path), data
}
