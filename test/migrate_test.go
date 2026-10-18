// Parity tests for Phase 6 Task 3: the Go migration runner against the deleted
// legacy package backend/db/migrations (runner/schema/seeds/steps,
// last version at 07204ee^). SCHEMA_VERSION stays 26; the cutover plan moves the
// version into PRAGMA user_version.
package tests

import (
	"database/sql"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/db"
)

func newMigrateDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "ovmanager.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return conn
}

func count(t *testing.T, conn *sql.DB, q string, args ...any) int {
	t.Helper()
	var n int
	if err := conn.QueryRow(q, args...).Scan(&n); err != nil {
		t.Fatalf("query %q: %v", q, err)
	}
	return n
}

func hasTable(t *testing.T, conn *sql.DB, name string) bool {
	t.Helper()
	return count(t, conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", name) > 0
}

func hasIndex(t *testing.T, conn *sql.DB, name string) bool {
	t.Helper()
	return count(t, conn, "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?", name) > 0
}

func hasColumn(t *testing.T, conn *sql.DB, table, col string) bool {
	t.Helper()
	rows, err := conn.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		t.Fatalf("table_info %s: %v", table, err)
	}
	defer rows.Close()
	for rows.Next() {
		var (
			cid, notnull, pk int
			name, ctype      string
			dflt             sql.NullString
		)
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			t.Fatalf("scan table_info: %v", err)
		}
		if name == col {
			return true
		}
	}
	return false
}

func userVersion(t *testing.T, conn *sql.DB) int {
	t.Helper()
	return count(t, conn, "PRAGMA user_version")
}

// TestMigrationStepListMatches pins the ordered step list to
// STEPS tuple verbatim — the runner's order and wording are the parity contract.
func TestMigrationStepListMatches(t *testing.T) {
	want := []db.MigrationStep{
		{2, "encrypt node API keys at rest"},
		{3, "drop orphan daily traffic rows"},
		{4, "add lookup indices"},
		{5, "add admin disabled flag"},
		{6, "add Telegram notification flags"},
		{7, "add automatic backup settings"},
		{8, "add user tag column"},
		{9, "add node-down alert flag"},
		{10, "add offsite backup target"},
		{11, "add encrypted Telegram backup setting"},
		{12, "seed owner row and first user"},
		{13, "add per-admin user defaults"},
		{14, "decrypt stored secrets (at-rest encryption retired)"},
		{15, "add node server_ca (TLS pinning)"},
		{16, "move the owner credential into the database"},
		{17, "add TLS/ACME and Telegram wizard settings"},
		{18, "add panel domain setting"},
		{19, "add threshold alert settings"},
		{20, "add subscription profile settings"},
		{21, "add panel identity (settings.panel_id)"},
		{22, "add admin owner flag (admins.is_owner)"},
		{23, "add event delivered markers (delivered)"},
		{24, "single-admin cut (drop multi-admin columns)"},
		{25, "add traffic ledger and settings kv"},
		{26, "unique owner index (admins.is_owner)"},
	}
	if db.SchemaVersion != 26 {
		t.Fatalf("SchemaVersion = %d, want 26", db.SchemaVersion)
	}
	got := db.MigrationSteps()
	if len(got) != len(want) {
		t.Fatalf("step count = %d, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("step[%d] = %+v, want %+v", i, got[i], want[i])
		}
	}
}

// TestMigrateFreshReachesHead builds a brand-new database at HEAD in one pass
// and proves a second run changes nothing (idempotent).
func TestMigrateFreshReachesHead(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	t.Setenv("DEFAULT_USER", "user1")
	t.Setenv("URLPATH", "")
	conn := newMigrateDB(t)

	v, err := db.Migrate(conn)
	if err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if v != 26 || userVersion(t, conn) != 26 {
		t.Fatalf("version = %d, user_version = %d, want 26", v, userVersion(t, conn))
	}

	for _, table := range []string{
		"users", "admins", "sessions", "nodes", "settings",
		"delivered", "traffic_ledger", "settings_kv", "login_attempts", "audit_logs",
	} {
		if !hasTable(t, conn, table) {
			t.Fatalf("fresh schema missing table %s", table)
		}
	}
	for _, col := range []struct{ table, name string }{
		{"users", "tag"}, {"settings", "panel_id"}, {"admins", "is_owner"}, {"nodes", "server_ca"},
	} {
		if !hasColumn(t, conn, col.table, col.name) {
			t.Fatalf("fresh schema missing column %s.%s", col.table, col.name)
		}
	}
	if !hasIndex(t, conn, "uq_admins_owner") {
		t.Fatalf("fresh schema missing partial unique index uq_admins_owner")
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM settings"); n != 1 {
		t.Fatalf("settings rows = %d, want 1", n)
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM admins WHERE is_owner = 1"); n != 1 {
		t.Fatalf("owner rows = %d, want 1", n)
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM users"); n != 1 {
		t.Fatalf("first user rows = %d, want 1", n)
	}

	// Second run: fully idempotent.
	v2, err := db.Migrate(conn)
	if err != nil {
		t.Fatalf("second Migrate: %v", err)
	}
	if v2 != 26 || userVersion(t, conn) != 26 {
		t.Fatalf("second run version = %d/%d, want 26", v2, userVersion(t, conn))
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM settings"); n != 1 {
		t.Fatalf("second run duplicated settings rows: %d", n)
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM admins"); n != 1 {
		t.Fatalf("second run duplicated admins rows: %d", n)
	}
	if n := count(t, conn, "SELECT COUNT(*) FROM users"); n != 1 {
		t.Fatalf("second run duplicated users rows: %d", n)
	}
}

const legacyUpgradeSchema = `
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR, total BIGINT, used BIGINT,
  last_node_usage BIGINT, node_usage VARCHAR, max_logins INTEGER, expiry_date DATE,
  is_active BOOLEAN, last_online DATETIME, owner VARCHAR);
CREATE TABLE admins (id INTEGER PRIMARY KEY, username VARCHAR, password VARCHAR, telegram_id INTEGER,
  username_prefix VARCHAR, disabled BOOLEAN);
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR, protocol VARCHAR,
  ovpn_port INTEGER, port INTEGER, key VARCHAR, status BOOLEAN);
CREATE TABLE settings (id INTEGER PRIMARY KEY, tunnel_address VARCHAR, port INTEGER,
  protocol VARCHAR, timezone VARCHAR, bot_token VARCHAR, bot_enabled BOOLEAN,
  default_days INTEGER, default_traffic_gb INTEGER, default_max_users INTEGER,
  owner_telegram_id INTEGER, subscription_url_prefix VARCHAR, subscription_path VARCHAR,
  urlpath VARCHAR);
CREATE TABLE user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL,
  bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day));
`

// TestMigrateUpgradesOlderDatabase starts from a stamped v3 database whose shape
// predates the later steps and asserts each missing piece lands.
func TestMigrateUpgradesOlderDatabase(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyUpgradeSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 3"); err != nil {
		t.Fatalf("stamp legacy: %v", err)
	}

	v, err := db.Migrate(conn)
	if err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if v != 26 || userVersion(t, conn) != 26 {
		t.Fatalf("version = %d/%d, want 26", v, userVersion(t, conn))
	}
	if !hasColumn(t, conn, "users", "tag") {
		t.Fatalf("v8 did not add users.tag")
	}
	if !hasColumn(t, conn, "settings", "notify_expiry") || !hasColumn(t, conn, "settings", "notify_traffic") {
		t.Fatalf("v6 did not add settings.notify_expiry/notify_traffic")
	}
	if !hasColumn(t, conn, "admins", "is_owner") {
		t.Fatalf("v22 did not add admins.is_owner")
	}
	if hasColumn(t, conn, "admins", "username_prefix") || hasColumn(t, conn, "users", "owner") {
		t.Fatalf("v24 did not drop the multi-admin columns")
	}
	if !hasIndex(t, conn, "idx_users_expiry") {
		t.Fatalf("v4 did not add idx_users_expiry")
	}
	if !hasTable(t, conn, "delivered") {
		t.Fatalf("v23 did not create delivered")
	}
	if !hasIndex(t, conn, "uq_admins_owner") {
		t.Fatalf("v26 did not create uq_admins_owner")
	}
}

// TestMigrateRefusesNewerDatabase mirrors runner.migrate's guard: a database
// stamped past HEAD is refused, not silently run.
func TestMigrateRefusesNewerDatabase(t *testing.T) {
	conn := newMigrateDB(t)
	if _, err := conn.Exec("CREATE TABLE users (id INTEGER PRIMARY KEY)"); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 99"); err != nil {
		t.Fatalf("stamp: %v", err)
	}
	_, err := db.Migrate(conn)
	if err == nil || !strings.Contains(err.Error(), "newer than this build supports") {
		t.Fatalf("Migrate error = %v, want newer-than-build refusal", err)
	}
}

// fernetKey/fernetToken were minted by cryptography.fernet over
// b"my-secret-bot-token" — the cross-implementation guard for v14.
const (
	fernetKey   = "Ilcce2f4KtuKc2lquXlc-hZx3Nki5n7Kt829kbXsI5A="
	fernetToken = "gAAAAABq0tun88MF4wduBBHJkGCmWExSdwv-vLnVvuGV0P6kz3f37ncLs5uChA_4GS0u50us4pP_si1AL0FL3qAhtFUpdJa4Pj9mf8L9bh6AGjXmkDN7KbI="
)

const legacyEncryptedSchema = `
CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_token VARCHAR);
CREATE TABLE nodes (id INTEGER PRIMARY KEY, key VARCHAR);
INSERT INTO settings (id, bot_token) VALUES (1, 'enc:` + fernetToken + `');
INSERT INTO nodes (id, key) VALUES (1, 'enc:` + fernetToken + `');
`

// TestMigrateDecryptsStoredSecrets proves a Go-built DB reads the Fernet
// rows at v14 (stdlib crypto, no new dependency).
func TestMigrateDecryptsStoredSecrets(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "")
	t.Setenv("BOT_ENCRYPT_KEY", fernetKey)
	t.Setenv("NODE_ENCRYPT_KEY", "")
	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyEncryptedSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 13"); err != nil {
		t.Fatalf("stamp: %v", err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	var bot, key string
	if err := conn.QueryRow("SELECT bot_token FROM settings WHERE id = 1").Scan(&bot); err != nil {
		t.Fatalf("read bot_token: %v", err)
	}
	if err := conn.QueryRow("SELECT key FROM nodes WHERE id = 1").Scan(&key); err != nil {
		t.Fatalf("read node key: %v", err)
	}
	if bot != "my-secret-bot-token" || key != "my-secret-bot-token" {
		t.Fatalf("decrypted bot=%q key=%q, want my-secret-bot-token", bot, key)
	}
}

// TestMigrateLeavesEncryptedRowsWithoutAKey is the fail-closed half: no key in
// the environment means the enc: rows are left untouched, never truncated.
func TestMigrateLeavesEncryptedRowsWithoutAKey(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "")
	t.Setenv("BOT_ENCRYPT_KEY", "")
	t.Setenv("NODE_ENCRYPT_KEY", "")
	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyEncryptedSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 13"); err != nil {
		t.Fatalf("stamp: %v", err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	var bot string
	if err := conn.QueryRow("SELECT bot_token FROM settings WHERE id = 1").Scan(&bot); err != nil {
		t.Fatalf("read bot_token: %v", err)
	}
	if bot != "enc:"+fernetToken {
		t.Fatalf("bot_token = %q, want the enc: row left untouched", bot)
	}
}
