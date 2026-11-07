package panel

import (
	"testing"
	"time"
)

// TestCleanupCandidatesDisabledFindsLoggedInUsers: a disabled user with a
// non-null last_online must match the disabled cleanup filter (DATETIME text
// vs date cutoff, not a float epoch).
func TestCleanupCandidatesDisabledFindsLoggedInUsers(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	if _, err := h.Svc.DB().Exec(`CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER, last_online TEXT, expiry_date TEXT)`); err != nil {
		t.Fatal(err)
	}
	oldDate := time.Now().UTC().AddDate(0, 0, -400).Format("2006-01-02 15:04:05")
	if _, err := h.Svc.DB().Exec(`INSERT INTO users (id, name, is_active, last_online) VALUES (1, 'old', 0, ?), (2, 'recent', 0, ?)`, oldDate, time.Now().UTC().Format("2006-01-02 15:04:05")); err != nil {
		t.Fatal(err)
	}
	got := h.cleanupCandidates(cleanupRequest{Status: "disabled", OlderThanDays: 30})
	ids := map[int64]bool{}
	for _, row := range got {
		ids[row["id"].(int64)] = true
	}
	if !ids[1] {
		t.Fatalf("disabled user with old last_online missing from %v", got)
	}
	if ids[2] {
		t.Fatalf("recently online disabled user must not match: %v", got)
	}
}
