package panel

import (
	"testing"
	"time"
)

// TestBackupTickOffsiteFailureDoesNotStampDay: local success is not offsite
// success; a failed offsite copy must not record the day, so the next tick
// retries.
func TestBackupTickOffsiteFailureDoesNotStampDay(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 1, "00:00", "UTC")
	if _, err := h.Svc.DB().Exec(`INSERT INTO settings (id, auto_backup_enabled, auto_backup_time, timezone, offsite_backup_target) VALUES (1, 1, '00:00', 'UTC', 'not-a-valid-target') ON CONFLICT(id) DO UPDATE SET offsite_backup_target = 'not-a-valid-target'`); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "" {
		t.Fatalf("offsite failure recorded day %q", got)
	}
}
