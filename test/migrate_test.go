// Parity tests for Phase 6 Task 3: the Go migration runner against the deleted
// last version at 07204ee^). SCHEMA_VERSION stays 28; the cutover plan moves the
// version into PRAGMA user_version.
package tests

import (
	"database/sql"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/crypto"
	"github.com/anonysec/OVManager/internal/db"
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
	if v != 36 || userVersion(t, conn) != 36 {
		t.Fatalf("version = %d, user_version = %d, want 36", v, userVersion(t, conn))
	}

	for _, table := range []string{
		"users", "admins", "sessions", "nodes", "settings",
		"delivered", "traffic_ledger",
		"pending_user_revocations",
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
	if v2 != 36 || userVersion(t, conn) != 36 {
		t.Fatalf("second run version = %d/%d, want 36", v2, userVersion(t, conn))
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
	if v != 36 || userVersion(t, conn) != 36 {
		t.Fatalf("version = %d/%d, want 36", v, userVersion(t, conn))
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
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)
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
	if !strings.HasPrefix(bot, crypto.EncPrefix) || !strings.HasPrefix(key, crypto.EncPrefix) {
		t.Fatalf("migrated bot=%q key=%q, want enc:v2:", bot, key)
	}
	decBot, err := crypto.DecryptSecret(bot, dir)
	if err != nil {
		t.Fatalf("decrypt bot: %v", err)
	}
	decKey, err := crypto.DecryptSecret(key, dir)
	if err != nil {
		t.Fatalf("decrypt key: %v", err)
	}
	if decBot != "my-secret-bot-token" || decKey != "my-secret-bot-token" {
		t.Fatalf("decrypted bot=%q key=%q, want my-secret-bot-token", decBot, decKey)
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

// collectTableNames returns the set of user tables in conn.
func collectTableNames(t *testing.T, conn *sql.DB) map[string]bool {
	t.Helper()
	rows, err := conn.Query("SELECT name FROM sqlite_master WHERE type='table'")
	if err != nil {
		t.Fatalf("tables: %v", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			t.Fatalf("scan table: %v", err)
		}
		out[n] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("tables rows: %v", err)
	}
	return out
}

// collectIndexNames returns the set of index names in conn.
func collectIndexNames(t *testing.T, conn *sql.DB) map[string]bool {
	t.Helper()
	rows, err := conn.Query("SELECT name FROM sqlite_master WHERE type='index'")
	if err != nil {
		t.Fatalf("indices: %v", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var n string
		if err := rows.Scan(&n); err != nil {
			t.Fatalf("scan index: %v", err)
		}
		// Auto-indices back UNIQUE/PK constraints declared in CREATE TABLE;
		// legacy tables carry different constraints, so compare explicit indices.
		if strings.HasPrefix(n, "sqlite_autoindex_") {
			continue
		}
		out[n] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("indices rows: %v", err)
	}
	return out
}

// collectColumns returns the set of column names for a table.
func collectColumns(t *testing.T, conn *sql.DB, table string) map[string]bool {
	t.Helper()
	rows, err := conn.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		t.Fatalf("table_info %s: %v", table, err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var (
			cid, notnull, pk int
			name, ctype      string
			dflt             sql.NullString
		)
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			t.Fatalf("scan table_info: %v", err)
		}
		out[name] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("table_info rows: %v", err)
	}
	return out
}

func equalStringSets(a, b map[string]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if !b[k] {
			return false
		}
	}
	return true
}

// TestMigrateFreshAndUpgradedConverge proves a fresh DB and an upgraded legacy
// DB end up with the same tables, indices and columns per table.
func TestMigrateFreshAndUpgradedConverge(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	t.Setenv("DEFAULT_USER", "user1")
	t.Setenv("URLPATH", "")

	fresh := newMigrateDB(t)
	if _, err := db.Migrate(fresh); err != nil {
		t.Fatalf("fresh Migrate: %v", err)
	}

	upgraded := newMigrateDB(t)
	if _, err := upgraded.Exec(legacyUpgradeSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := upgraded.Exec("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (1, '2026-01-01', 100)"); err != nil {
		t.Fatalf("legacy traffic row: %v", err)
	}
	if _, err := upgraded.Exec("PRAGMA user_version = 3"); err != nil {
		t.Fatalf("stamp legacy: %v", err)
	}
	if _, err := db.Migrate(upgraded); err != nil {
		t.Fatalf("upgraded Migrate: %v", err)
	}

	// tables
	ft, ut := collectTableNames(t, fresh), collectTableNames(t, upgraded)
	if !equalStringSets(ft, ut) {
		t.Fatalf("table sets differ: fresh=%v upgraded=%v", ft, ut)
	}
	// indices
	fi, ui := collectIndexNames(t, fresh), collectIndexNames(t, upgraded)
	if !equalStringSets(fi, ui) {
		t.Fatalf("index sets differ: fresh=%v upgraded=%v", fi, ui)
	}
	// columns per table
	for table := range ft {
		fc := collectColumns(t, fresh, table)
		uc := collectColumns(t, upgraded, table)
		if !equalStringSets(fc, uc) {
			t.Fatalf("columns for %s differ: fresh=%v upgraded=%v", table, fc, uc)
		}
	}
}

// TestMigrateV25BackfillRerunnable proves re-running the v25 backfill (after a
// simulated crash between insert and stamp) does not hit the unique constraint.
func TestMigrateV25BackfillRerunnable(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	t.Setenv("DEFAULT_USER", "user1")
	t.Setenv("URLPATH", "")

	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyUpgradeSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (1, '2026-01-01', 100)"); err != nil {
		t.Fatalf("legacy traffic row: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 3"); err != nil {
		t.Fatalf("stamp legacy: %v", err)
	}

	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("first Migrate: %v", err)
	}
	var first int
	if err := conn.QueryRow("SELECT COUNT(*) FROM traffic_ledger").Scan(&first); err != nil {
		t.Fatalf("count ledger: %v", err)
	}

	// Simulate crash-after-backfill-before-stamp: roll the version back to 24.
	if _, err := conn.Exec("PRAGMA user_version = 24"); err != nil {
		t.Fatalf("rollback stamp: %v", err)
	}
	v, err := db.Migrate(conn)
	if err != nil {
		t.Fatalf("second Migrate: %v", err)
	}
	if v != 36 {
		t.Fatalf("version = %d, want 36", v)
	}
	var second int
	if err := conn.QueryRow("SELECT COUNT(*) FROM traffic_ledger").Scan(&second); err != nil {
		t.Fatalf("count ledger: %v", err)
	}
	if second != first {
		t.Fatalf("ledger rows changed: %d -> %d", first, second)
	}
}

// An older database can hold more than one is_owner row: step 22 flags the
// owner active, and the legacy import path can add another. Step 28 is what
// dedupes them, and the UNIQUE index it creates must come AFTER that dedupe
// — creating the index first makes such an upgrade fail outright.
func TestMigrateDeduplicatesOwnersBeforeTheUniqueIndex(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyUpgradeSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec(`ALTER TABLE admins ADD COLUMN is_owner BOOLEAN DEFAULT 0`); err != nil {
		t.Fatalf("add is_owner: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('owner-a', 'x', 1)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('owner-b', 'x', 1)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 25"); err != nil {
		t.Fatalf("stamp: %v", err)
	}

	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("Migrate refused a database with two owner rows: %v", err)
	}
	var owners int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM admins WHERE is_owner = 1`).Scan(&owners); err != nil {
		t.Fatal(err)
	}
	if owners != 1 {
		t.Errorf("owner rows = %d, want 1", owners)
	}
	if !hasIndex(t, conn, "uq_admins_owner") {
		t.Error("uq_admins_owner missing")
	}
}

// A pre-runner database (user_version 0) can hold more than one is_owner row
// as well. Its path creates the mapped tables up front, so the unique index
// must not be created there either: the panel has to start, dedupe the rows
// and end up with one owner.
func TestMigratePreRunnerDatabaseDeduplicatesOwners(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	conn := newMigrateDB(t)
	if _, err := conn.Exec(legacyUpgradeSchema); err != nil {
		t.Fatalf("legacy schema: %v", err)
	}
	if _, err := conn.Exec(`ALTER TABLE admins ADD COLUMN is_owner BOOLEAN DEFAULT 0`); err != nil {
		t.Fatalf("add is_owner: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('owner-a', 'x', 1)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('owner-b', 'x', 1)`); err != nil {
		t.Fatal(err)
	}

	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("Migrate refused a pre-runner database with two owner rows: %v", err)
	}
	var owners int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM admins WHERE is_owner = 1`).Scan(&owners); err != nil {
		t.Fatal(err)
	}
	if owners != 1 {
		t.Errorf("owner rows = %d, want 1", owners)
	}
	if !hasIndex(t, conn, "uq_admins_owner") {
		t.Error("uq_admins_owner missing")
	}
}

// TestDeletedHighestUserIDIsNotReused: AUTOINCREMENT keeps a deleted highest id
// from being handed to the next account.
func TestDeletedHighestUserIDIsNotReused(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	conn := newMigrateDB(t)
	if _, err := db.Migrate(conn); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	// insert two users, capture the higher id
	res, err := conn.Exec(`INSERT INTO users (uuid, name, max_logins, expiry_date, is_active, used) VALUES (?, ?, 1, date('now','+30 days'), 1, 0)`, "u-1", "u1")
	if err != nil {
		t.Fatalf("insert u1: %v", err)
	}
	id1, _ := res.LastInsertId()
	res, err = conn.Exec(`INSERT INTO users (uuid, name, max_logins, expiry_date, is_active, used) VALUES (?, ?, 1, date('now','+30 days'), 1, 0)`, "u-2", "u2")
	if err != nil {
		t.Fatalf("insert u2: %v", err)
	}
	id2, _ := res.LastInsertId()
	higher := id1
	if id2 > higher {
		higher = id2
	}
	// delete the highest-id account
	if _, err := conn.Exec(`DELETE FROM users WHERE id = ?`, higher); err != nil {
		t.Fatalf("delete: %v", err)
	}
	// insert another
	res, err = conn.Exec(`INSERT INTO users (uuid, name, max_logins, expiry_date, is_active, used) VALUES (?, ?, 1, date('now','+30 days'), 1, 0)`, "u-3", "u3")
	if err != nil {
		t.Fatalf("insert u3: %v", err)
	}
	newID, _ := res.LastInsertId()
	if newID <= higher {
		t.Fatalf("new id %d not greater than deleted highest %d", newID, higher)
	}
}

// TestRevocationMigrationPreservesUsers: a v28 database's users and related rows
// survive the v29 rebuild with values intact.
func TestRevocationMigrationPreservesUsers(t *testing.T) {
	t.Setenv("ADMIN_USERNAME", "migrate-owner")
	t.Setenv("ADMIN_PASSWORD_HASH", "")
	conn := newMigrateDB(t)
	// legacy v28-shaped users table (no AUTOINCREMENT) with one row
	if _, err := conn.Exec(`CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR, total BIGINT, used BIGINT,
		last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}', max_logins INTEGER DEFAULT 1, expiry_date DATE,
		is_active BOOLEAN DEFAULT 1, last_online DATETIME, tag VARCHAR)`); err != nil {
		t.Fatalf("legacy users: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name, total, used, max_logins, expiry_date, is_active, tag) VALUES (42, 'uuid-42', 'alice', 1000, 500, 3, '2026-12-31', 1, 'vip')`); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	if _, err := conn.Exec(`CREATE TABLE nodes (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR, protocol VARCHAR, ovpn_port INTEGER, port INTEGER, key VARCHAR, status BOOLEAN)`); err != nil {
		t.Fatalf("nodes: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO nodes (id, name, address, protocol, ovpn_port, port, key, status) VALUES (7, 'n1', '1.2.3.4', 'tcp', 1194, 1194, 'secretkey', 1)`); err != nil {
		t.Fatalf("insert node: %v", err)
	}
	if _, err := conn.Exec(`CREATE TABLE settings (id INTEGER PRIMARY KEY)`); err != nil {
		t.Fatalf("settings: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO settings (id) VALUES (1)`); err != nil {
		t.Fatalf("settings row: %v", err)
	}
	if _, err := conn.Exec(`CREATE TABLE user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day))`); err != nil {
		t.Fatalf("daily: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (42, '2026-01-01', 123)`); err != nil {
		t.Fatalf("daily row: %v", err)
	}
	// A deleted-user undo snapshot holding an ID above every live row: the
	// AUTOINCREMENT sequence must be seeded past it, or the ID would be
	// reissued and stale node CNs would resolve to the new account.
	if _, err := conn.Exec(`CREATE TABLE deleted_users (uuid TEXT PRIMARY KEY, snap_json TEXT NOT NULL, deleted_at REAL NOT NULL, expires_at REAL NOT NULL)`); err != nil {
		t.Fatalf("deleted_users: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO deleted_users (uuid, snap_json, deleted_at, expires_at) VALUES ('uuid-gone', '{"ID":777,"UUID":"uuid-gone","Name":"gone"}', 1, 9999999999)`); err != nil {
		t.Fatalf("snapshot row: %v", err)
	}
	// Legacy lowercase-key snapshot: must also seed past it.
	if _, err := conn.Exec(`INSERT INTO deleted_users (uuid, snap_json, deleted_at, expires_at) VALUES ('uuid-gone2', '{"id":888,"uuid":"uuid-gone2","name":"gone2"}', 1, 9999999999)`); err != nil {
		t.Fatalf("lowercase snapshot row: %v", err)
	}
	// A corrupt snapshot is unrecoverable and must be skipped, not fatal.
	if _, err := conn.Exec(`INSERT INTO deleted_users (uuid, snap_json, deleted_at, expires_at) VALUES ('uuid-bad', 'not json{{{', 1, 9999999999)`); err != nil {
		t.Fatalf("corrupt snapshot row: %v", err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 28"); err != nil {
		t.Fatalf("stamp: %v", err)
	}

	v, err := db.Migrate(conn)
	if err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	if v != 36 {
		t.Fatalf("version = %d, want 36", v)
	}
	// user preserved
	var id int64
	var uuid, name, tag string
	var total, used int64
	var maxlogins int
	var expiry string
	var isactive int
	if err := conn.QueryRow(`SELECT id, uuid, name, total, used, max_logins, expiry_date, is_active, tag FROM users WHERE id=42`).Scan(&id, &uuid, &name, &total, &used, &maxlogins, &expiry, &isactive, &tag); err != nil {
		t.Fatalf("read user: %v", err)
	}
	if id != 42 || uuid != "uuid-42" || name != "alice" || total != 1000 || used != 500 || maxlogins != 3 || !strings.HasPrefix(expiry, "2026-12-31") || isactive != 1 || tag != "vip" {
		t.Fatalf("user not preserved: %+v", map[string]any{"id": id, "uuid": uuid, "name": name, "total": total, "used": used, "max": maxlogins, "exp": expiry, "active": isactive, "tag": tag})
	}
	// daily preserved
	if n := count(t, conn, "SELECT COUNT(*) FROM user_traffic_daily WHERE user_id=42"); n != 1 {
		t.Fatalf("daily row lost")
	}
	// pending table exists
	if !hasTable(t, conn, "pending_user_revocations") {
		t.Fatalf("pending_user_revocations missing")
	}
	// node secret preserved
	var key string
	if err := conn.QueryRow("SELECT key FROM nodes WHERE id=7").Scan(&key); err != nil || key != "secretkey" {
		t.Fatalf("node not preserved: %v %s", err, key)
	}
	// sequence seeded past the deleted snapshot IDs (777, 888), not just live max
	res, err := conn.Exec(`INSERT INTO users (uuid, name, max_logins, expiry_date, is_active, used) VALUES ('uuid-new', 'newuser', 1, date('now','+30 days'), 1, 0)`)
	if err != nil {
		t.Fatalf("insert after migrate: %v", err)
	}
	newID, _ := res.LastInsertId()
	if newID <= 888 {
		t.Fatalf("new id %d not greater than deleted snapshot ids 777/888", newID)
	}
	// foreign key check clean (should return no rows)
	rows, err := conn.Query("PRAGMA foreign_key_check")
	if err != nil {
		t.Fatalf("fk check: %v", err)
	}
	defer rows.Close()
	if rows.Next() {
		t.Fatalf("foreign_key_check returned rows")
	}
}

// TestMigrateDropsUnusableAuditIndex removed: audit_logs table dropped.
