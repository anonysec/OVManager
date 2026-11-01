// Daily database backup worker: replaces the ovmanager-backup systemd timer.
// Runs once per day inside the panel process.
package panel

import (
	"log"
	"sync"
	"time"
)

const backupWorkerInterval = 24 * time.Hour
const backupWorkerBootDelay = 5 * time.Minute

var backupWorkerOnce sync.Once

func (h *Handler) startBackupWorker() {
	backupWorkerOnce.Do(func() {
		go func() {
			defer func() { recover() }()
			time.Sleep(backupWorkerBootDelay)
			ticker := time.NewTicker(backupWorkerInterval)
			defer ticker.Stop()
			for range ticker.C {
				runGuarded("backup worker", h.backupTick)
			}
		}()
	})
}

func (h *Handler) backupTick() {
	path, err := h.createPanelBackup(7, "backup")
	if err != nil {
		log.Printf("backup worker: %v", err)
		return
	}
	if path != "" {
		log.Printf("backup worker: created %s", path)
	}
}
