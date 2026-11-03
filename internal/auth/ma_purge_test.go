package auth

import (
	"database/sql"
	"testing"

	_ "modernc.org/sqlite"
)

func TestPurgeExpiredLoginAttempts(t *testing.T) {
	d := setupAuthTestDB(t)
	svc := NewService(d, t.TempDir())
	now := nowSecs()
	// expired row
	_, _ = d.Exec(`INSERT INTO login_attempts (key_hash, attempts, updated) VALUES ('expired', '[]', ?)`, now-float64(lockoutSeconds)-10)
	// fresh row
	_, _ = d.Exec(`INSERT INTO login_attempts (key_hash, attempts, updated) VALUES ('fresh', '[]', ?)`, now-10)
	n := svc.PurgeExpired()
	if n < 1 {
		t.Fatalf("PurgeExpired removed %d, want >=1", n)
	}
	var cnt int
	if err := d.QueryRow(`SELECT COUNT(*) FROM login_attempts`).Scan(&cnt); err != nil {
		t.Fatal(err)
	}
	if cnt != 1 {
		t.Fatalf("remaining rows = %d, want 1", cnt)
	}
}

func TestLoginAttemptsTableCap(t *testing.T) {
	d := setupAuthTestDB(t)
	svc := NewService(d, t.TempDir())
	now := nowSecs()
	// Insert more than cap
	for i := 0; i < 10005; i++ {
		_, _ = d.Exec(`INSERT INTO login_attempts (key_hash, attempts, updated) VALUES (?, '[]', ?)`, sql.NullString{String: "k" + itoa(i), Valid: true}.String, now-float64(i))
	}
	_ = svc.PurgeExpired()
	var cnt int
	_ = d.QueryRow(`SELECT COUNT(*) FROM login_attempts`).Scan(&cnt)
	if cnt > 10000 {
		t.Fatalf("table cap not enforced: %d rows", cnt)
	}
}

func itoa(i int) string {
	// avoid strconv import noise
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var digits []byte
	for i > 0 {
		digits = append([]byte{byte('0' + i%10)}, digits...)
		i /= 10
	}
	if neg {
		return "-" + string(digits)
	}
	return string(digits)
}
