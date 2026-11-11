package panel

import (
	"database/sql"
	"path/filepath"
	"testing"
	"time"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

func newBackupTestHandler(t *testing.T) (*Handler, string) {
	t.Helper()
	dataDir := t.TempDir()
	t.Setenv("DataDir", dataDir)
	conn, err := db.Open(filepath.Join(dataDir, "panel.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE Setting (
		id INTEGER PRIMARY KEY, auto_backup_enabled INTEGER DEFAULT 0,
		auto_backup_time TEXT DEFAULT '03:30', auto_backup_keep INTEGER DEFAULT 50,
		timezone TEXT DEFAULT 'UTC', offsite_backup_target TEXT DEFAULT '',
		backup_last_success_day TEXT);
CREATE TABLE telemetry (id INTEGER PRIMARY KEY);`); err != nil {
		t.Fatal(err)
	}
	return NewHandler(auth.NewService(conn, dataDir)), dataDir
}

func setBackupSettings(t *testing.T, h *Handler, enabled int, timeStr, tz string) {
	t.Helper()
	if _, err := h.Svc.DB().Exec(
		`INSERT INTO Setting (id, auto_backup_enabled, auto_backup_time, timezone) VALUES (1, ?, ?, ?)
		 ON CONFLICT(id) DO UPDATE SET auto_backup_enabled = ?, auto_backup_time = ?, timezone = ?`,
		enabled, timeStr, tz, enabled, timeStr, tz); err != nil {
		t.Fatal(err)
	}
}

func lastSuccessDay(t *testing.T, h *Handler) string {
	t.Helper()
	var v sql.NullString
	_ = h.Svc.DB().QueryRow(`SELECT backup_last_success_day FROM Setting ORDER BY id LIMIT 1`).Scan(&v)
	if v.Valid {
		return v.String
	}
	return ""
}

func TestBackupTickDisabledDoesNothing(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 0, "00:00", "UTC")
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "" {
		t.Fatalf("disabled backup recorded day %q", got)
	}
}

func TestBackupTickBeforeScheduleDoesNothing(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 1, "03:30", "UTC")
	now := time.Date(2026, 11, 6, 2, 0, 0, 0, time.UTC) // before 03:30 local
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "" {
		t.Fatalf("before-schedule backup recorded day %q", got)
	}
}

func TestBackupTickInvalidTimezoneDoesNothing(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 1, "00:00", "Not/AZone")
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "" {
		t.Fatalf("invalid-timezone backup recorded day %q", got)
	}
}

func TestBackupTickInvalidTimeDoesNothing(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 1, "33:99", "UTC")
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "" {
		t.Fatalf("invalid-time backup recorded day %q", got)
	}
}

func TestBackupTickSameDaySkipped(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	setBackupSettings(t, h, 1, "03:30", "UTC")
	if _, err := h.Svc.DB().Exec(`INSERT INTO Setting (id, backup_last_success_day) VALUES (1, '2026-11-06') ON CONFLICT(id) DO UPDATE SET backup_last_success_day = '2026-11-06'`); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC) // after schedule, same day already done
	h.backupTickAt(now)
	if got := lastSuccessDay(t, h); got != "2026-11-06" {
		t.Fatalf("same-day record changed to %q", got)
	}
}
