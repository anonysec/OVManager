// Schema migration runner, ported from the deleted Python package
// backend/db/migrations (last version at 07204ee^: runner.py, schema.py,
// seeds.py, steps.py, constants.py).
//
// The numbered steps are reproduced one-for-one, in order, with the same guards
// so a database is upgraded exactly like the Python runner did. The difference
// the cutover plan prescribes: the version lives in PRAGMA user_version instead
// of the schema_version table (no table survives, nothing to inspect).
//
// SCHEMA_VERSION stays 26 (Phase 6.2).
package db

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"fmt"
	"os"
	"strings"

	"github.com/google/uuid"
)

// SchemaVersion is the HEAD schema version (constants.SCHEMA_VERSION).
const SchemaVersion = 26

// MigrationStep is one numbered, ordered schema step (steps.STEPS).
type MigrationStep struct {
	Version     int
	Description string
}

// execer is the slice of *sql.DB the runner uses; *sql.Tx satisfies it too.
type execer interface {
	Exec(query string, args ...any) (sql.Result, error)
	Query(query string, args ...any) (*sql.Rows, error)
	QueryRow(query string, args ...any) *sql.Row
}

// Migrate brings conn up to SchemaVersion. Idempotent: a database already at
// HEAD is left untouched. A fresh database is built at HEAD and stamped; a
// database stamped below HEAD runs the remaining steps in order.
func Migrate(conn *sql.DB) (int, error) {
	before, err := userVersion(conn)
	if err != nil {
		return 0, err
	}

	tables := tableNames(conn)
	fresh := true
	for _, t := range mappedTableOrder {
		if tables[t] {
			fresh = false
			break
		}
	}

	if fresh {
		if err := createMappedTables(conn); err != nil {
			return 0, err
		}
		if err := createExtraTables(conn); err != nil {
			return 0, err
		}
		if _, err := reconcileColumns(conn); err != nil {
			return 0, err
		}
		if err := seedSettings(conn); err != nil {
			return 0, err
		}
		if err := seedOwnerAndFirstUser(conn); err != nil {
			return 0, err
		}
		if err := importOwnerCredential(conn); err != nil {
			return 0, err
		}
		if err := stamp(conn, SchemaVersion); err != nil {
			return 0, err
		}
		return SchemaVersion, nil
	}

	if before == 0 {
		// Adopt a pre-runner database: bring it to HEAD's shape, stamp v1.
		if err := createMappedTables(conn); err != nil {
			return 0, err
		}
		if err := createExtraTables(conn); err != nil {
			return 0, err
		}
		if _, err := reconcileColumns(conn); err != nil {
			return 0, err
		}
		if err := seedSettings(conn); err != nil {
			return 0, err
		}
		if err := stamp(conn, 1); err != nil {
			return 0, err
		}
		before = 1
	}

	if before > SchemaVersion {
		return before, fmt.Errorf(
			"database schema version %d is newer than this build supports (%d); update OVManager or restore an older database",
			before, SchemaVersion)
	}

	for _, s := range steps {
		if s.version <= before {
			continue
		}
		if err := s.run(conn); err != nil {
			return before, fmt.Errorf("migration v%d (%s): %w", s.version, s.description, err)
		}
		if err := stamp(conn, s.version); err != nil {
			return before, err
		}
		before = s.version
	}

	if err := createExtraTables(conn); err != nil {
		return 0, err
	}
	if err := seedSettings(conn); err != nil {
		return 0, err
	}
	return SchemaVersion, nil
}

// MigrationSteps exposes the ordered step list so a parity test can pin it to
// steps.py verbatim.
func MigrationSteps() []MigrationStep {
	out := make([]MigrationStep, len(steps))
	for i, s := range steps {
		out[i] = MigrationStep{Version: s.version, Description: s.description}
	}
	return out
}

// --- version tracking (PRAGMA user_version; schema.py current_version/_stamp) ---

func userVersion(x execer) (int, error) {
	var v int
	if err := x.QueryRow("PRAGMA user_version").Scan(&v); err != nil {
		return 0, fmt.Errorf("read user_version: %w", err)
	}
	return v, nil
}

func stamp(x execer, version int) error {
	// version is our own int, never user input.
	_, err := x.Exec(fmt.Sprintf("PRAGMA user_version = %d", version))
	return err
}

// --- schema inspection (schema.py table_names/column_names) ---

func tableNames(x execer) map[string]bool {
	out := map[string]bool{}
	rows, err := x.Query("SELECT name FROM sqlite_master WHERE type = 'table'")
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var name string
		if rows.Scan(&name) == nil {
			out[name] = true
		}
	}
	return out
}

func columnNames(x execer, table string) map[string]bool {
	out := map[string]bool{}
	rows, err := x.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var (
			cid, notnull, pk int
			name, ctype      string
			dflt             sql.NullString
		)
		if rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk) == nil {
			out[name] = true
		}
	}
	return out
}

// --- mapped-table construction (models.py + create_all) ---

type mcolumn struct {
	name string
	add  string // "TYPE [DEFAULT x] [NOT NULL]"
}

// mappedTableOrder is create_all's (dependency-free) table set.
var mappedTableOrder = []string{"admins", "sessions", "users", "nodes", "settings"}

// mappedColumns mirrors backend/db/models.py. The "add" tails carry the
// SQL literal a column needs when ALTER TABLE ADD COLUMN synthesises it, so the
// same list drives both CREATE TABLE and legacy-column reconciliation.
var mappedColumns = map[string][]mcolumn{
	"admins": {
		{"id", "INTEGER"},
		{"username", "VARCHAR DEFAULT '' NOT NULL"},
		{"password", "VARCHAR DEFAULT '' NOT NULL"},
		{"is_owner", "BOOLEAN DEFAULT 0 NOT NULL"},
		{"telegram_id", "INTEGER"},
	},
	"sessions": {
		{"id", "INTEGER"},
		{"token_hash", "VARCHAR DEFAULT '' NOT NULL"},
		{"username", "VARCHAR DEFAULT '' NOT NULL"},
		{"role", "VARCHAR DEFAULT '' NOT NULL"},
		{"created_at", "FLOAT DEFAULT 0 NOT NULL"},
		{"expires_at", "FLOAT DEFAULT 0 NOT NULL"},
		{"last_seen_at", "FLOAT DEFAULT 0 NOT NULL"},
		{"user_agent", "VARCHAR"},
		{"ip", "VARCHAR"},
	},
	"users": {
		{"id", "INTEGER"},
		{"uuid", "VARCHAR"},
		{"name", "VARCHAR DEFAULT '' NOT NULL"},
		{"total", "BIGINT"},
		{"used", "BIGINT"},
		{"last_node_usage", "BIGINT DEFAULT 0 NOT NULL"},
		{"node_usage", "VARCHAR DEFAULT '{}' NOT NULL"},
		{"max_logins", "INTEGER DEFAULT 1 NOT NULL"},
		{"expiry_date", "DATE DEFAULT CURRENT_TIMESTAMP NOT NULL"},
		{"is_active", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"last_online", "DATETIME"},
		{"tag", "VARCHAR"},
	},
	"nodes": {
		{"id", "INTEGER"},
		{"name", "VARCHAR DEFAULT '' NOT NULL"},
		{"address", "VARCHAR DEFAULT '' NOT NULL"},
		{"tunnel_address", "VARCHAR"},
		{"protocol", "VARCHAR DEFAULT '' NOT NULL"},
		{"ovpn_port", "INTEGER DEFAULT 0 NOT NULL"},
		{"port", "INTEGER DEFAULT 0 NOT NULL"},
		{"key", "VARCHAR DEFAULT '' NOT NULL"},
		{"status", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"server_ca", "VARCHAR"},
		{"country_code", "VARCHAR"},
		{"latitude", "FLOAT"},
		{"longitude", "FLOAT"},
	},
	"settings": {
		{"id", "INTEGER"},
		{"tunnel_address", "VARCHAR"},
		{"port", "INTEGER DEFAULT 1194 NOT NULL"},
		{"protocol", "VARCHAR DEFAULT 'tcp' NOT NULL"},
		{"timezone", "VARCHAR DEFAULT 'UTC' NOT NULL"},
		{"bot_token", "VARCHAR"},
		{"bot_enabled", "BOOLEAN DEFAULT 0 NOT NULL"},
		{"default_days", "INTEGER DEFAULT 30 NOT NULL"},
		{"default_traffic_gb", "INTEGER DEFAULT 100 NOT NULL"},
		{"default_max_users", "INTEGER DEFAULT 1 NOT NULL"},
		{"owner_telegram_id", "INTEGER"},
		{"notify_expiry", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"notify_traffic", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"notify_node_down", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"alert_days_left", "INTEGER DEFAULT 3 NOT NULL"},
		{"alert_usage_enabled", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"alert_usage_pct", "INTEGER DEFAULT 80 NOT NULL"},
		{"alert_cpu_enabled", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"alert_cpu_pct", "INTEGER DEFAULT 85 NOT NULL"},
		{"subscription_url_prefix", "VARCHAR"},
		{"subscription_path", "VARCHAR DEFAULT 'sub' NOT NULL"},
		{"sub_profile_title", "VARCHAR DEFAULT 'OVManager VPN' NOT NULL"},
		{"sub_support_url", "VARCHAR DEFAULT '' NOT NULL"},
		{"sub_announce", "VARCHAR DEFAULT '' NOT NULL"},
		{"sub_update_interval_hours", "INTEGER DEFAULT 12 NOT NULL"},
		{"urlpath", "VARCHAR DEFAULT '' NOT NULL"},
		{"auto_backup_enabled", "BOOLEAN DEFAULT 0 NOT NULL"},
		{"auto_backup_time", "VARCHAR DEFAULT '03:30' NOT NULL"},
		{"auto_backup_keep", "INTEGER DEFAULT 50 NOT NULL"},
		{"offsite_backup_target", "VARCHAR"},
		{"telegram_backup_enabled", "BOOLEAN DEFAULT 0 NOT NULL"},
		{"ssl_cert_file", "VARCHAR"},
		{"ssl_key_file", "VARCHAR"},
		{"acme_domain", "VARCHAR"},
		{"acme_email", "VARCHAR"},
		{"cert_method", "VARCHAR DEFAULT 'selfsigned' NOT NULL"},
		{"panel_id", "VARCHAR DEFAULT '' NOT NULL"},
		{"panel_url", "VARCHAR"},
		{"panel_domain", "VARCHAR"},
		{"bot_owner_setup_complete", "BOOLEAN DEFAULT 0 NOT NULL"},
	},
}

// mappedUniques are the model-level UNIQUE constraints create_all emits.
var mappedUniques = map[string][]string{
	"admins":   {"username", "telegram_id"},
	"sessions": {"token_hash"},
	"users":    {"uuid", "name"},
}

// mappedIndices are the model-level (partial) indices create_all emits.
var mappedIndices = []string{
	"CREATE UNIQUE INDEX IF NOT EXISTS uq_admins_owner ON admins (is_owner) WHERE is_owner = 1",
	"CREATE INDEX IF NOT EXISTS ix_sessions_username ON sessions (username)",
}

func createMappedTables(x execer) error {
	for _, table := range mappedTableOrder {
		if _, err := x.Exec(createTableSQL(table)); err != nil {
			return err
		}
	}
	for _, stmt := range mappedIndices {
		if _, err := x.Exec(stmt); err != nil {
			return err
		}
	}
	return nil
}

func createTableSQL(table string) string {
	cols := mappedColumns[table]
	parts := make([]string, 0, len(cols)+len(mappedUniques[table])+1)
	for _, c := range cols {
		parts = append(parts, c.name+" "+c.add)
	}
	parts = append(parts, "PRIMARY KEY (id)")
	for _, u := range mappedUniques[table] {
		parts = append(parts, "UNIQUE ("+u+")")
	}
	return "CREATE TABLE IF NOT EXISTS " + table + " (\n  " + strings.Join(parts, ",\n  ") + "\n)"
}

// extraTables is constants._EXTRA_DDL: the non-ORM tables.
var extraTables = []string{
	`CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT)`,
	`CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)`,
	`CREATE TABLE IF NOT EXISTS node_health_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, node_id INTEGER, node_name TEXT, cpu REAL, memory REAL, live_count INTEGER, latency_ms REAL, reachable INTEGER NOT NULL DEFAULT 0)`,
	`CREATE INDEX IF NOT EXISTS idx_node_health_ts ON node_health_snapshots(ts)`,
	`CREATE INDEX IF NOT EXISTS idx_node_health_node_ts ON node_health_snapshots(node_id, ts)`,
	`CREATE TABLE IF NOT EXISTS traffic_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, total_used REAL NOT NULL, active_connections INTEGER NOT NULL, online_users INTEGER NOT NULL, active_users INTEGER NOT NULL, total_users INTEGER NOT NULL)`,
	`CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)`,
	`CREATE TABLE IF NOT EXISTS security_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, auth_errors INTEGER NOT NULL, rejects INTEGER NOT NULL, stale_markers INTEGER NOT NULL, offline_nodes INTEGER NOT NULL, full_users INTEGER NOT NULL, inactive_users INTEGER NOT NULL)`,
	`CREATE INDEX IF NOT EXISTS idx_security_snapshots_ts ON security_snapshots(ts)`,
	`CREATE TABLE IF NOT EXISTS login_attempts (key_hash TEXT PRIMARY KEY, attempts TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL DEFAULT 0)`,
	`CREATE TABLE IF NOT EXISTS user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day))`,
	`CREATE INDEX IF NOT EXISTS idx_user_traffic_day ON user_traffic_daily(day)`,
	`CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`,
	`CREATE TABLE IF NOT EXISTS traffic_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id INTEGER NOT NULL, node_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, delta_bytes INTEGER NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}', UNIQUE (user_id, ts, kind, node_id))`,
	`CREATE INDEX IF NOT EXISTS idx_traffic_ledger_user_ts ON traffic_ledger(user_id, ts)`,
	`CREATE TABLE IF NOT EXISTS settings_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL DEFAULT 0)`,
}

func createExtraTables(x execer) error {
	for _, ddl := range extraTables {
		if _, err := x.Exec(ddl); err != nil {
			return err
		}
	}
	return nil
}

// reconcileColumns adds mapped columns missing from an existing table
// (schema.py _reconcile_columns): the one thing create_all cannot do.
func reconcileColumns(x execer) ([]string, error) {
	present := tableNames(x)
	var added []string
	for _, table := range mappedTableOrder {
		if !present[table] {
			continue
		}
		have := columnNames(x, table)
		for _, c := range mappedColumns[table] {
			if have[c.name] {
				continue
			}
			if _, err := x.Exec("ALTER TABLE " + table + " ADD COLUMN " + c.name + " " + c.add); err != nil {
				return added, err
			}
			added = append(added, table+"."+c.name)
		}
	}
	return added, nil
}

func addColumn(x execer, table, name, add string) error {
	if columnNames(x, table)[name] {
		return nil
	}
	_, err := x.Exec("ALTER TABLE " + table + " ADD COLUMN " + name + " " + add)
	return err
}

// --- first-run seeds (seeds.py) ---

func seedSettings(x execer) error {
	var n int
	if err := x.QueryRow("SELECT COUNT(*) FROM settings").Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	urlpath := strings.Trim(strings.TrimSpace(os.Getenv("URLPATH")), `"'`)
	urlpath = strings.Trim(urlpath, "/")
	_, err := x.Exec(
		`INSERT INTO settings
		 (port, protocol, timezone, bot_enabled, default_days, default_traffic_gb, default_max_users,
		  notify_expiry, notify_traffic, notify_node_down, alert_days_left, alert_usage_enabled,
		  alert_usage_pct, alert_cpu_enabled, alert_cpu_pct, subscription_path, sub_profile_title,
		  sub_support_url, sub_announce, sub_update_interval_hours, urlpath, auto_backup_enabled,
		  auto_backup_time, auto_backup_keep, telegram_backup_enabled, cert_method, panel_id,
		  bot_owner_setup_complete)
		 VALUES (1194, 'tcp', 'UTC', 0, 30, 100, 1, 1, 1, 1, 3, 1, 80, 1, 85, 'sub',
		  'OVManager VPN', '', '', 12, ?, 0, '03:30', 50, 0, 'selfsigned', ?, 0)`,
		urlpath, uuid.NewString())
	return err
}

func seedOwnerAndFirstUser(x execer) error {
	owner := envDefault("ADMIN_USERNAME", "admin")
	seeded := false
	if owner != "" {
		var n int
		if err := x.QueryRow("SELECT COUNT(*) FROM admins WHERE username = ?", owner).Scan(&n); err != nil {
			return err
		}
		if n == 0 {
			// is_owner only exists once v22/v24 has run (seeds.py guards this).
			if columnNames(x, "admins")["is_owner"] {
				if _, err := x.Exec("INSERT INTO admins (username, password, is_owner) VALUES (?, '', 1)", owner); err != nil {
					return err
				}
			} else if _, err := x.Exec("INSERT INTO admins (username, password) VALUES (?, '')", owner); err != nil {
				return err
			}
			seeded = true
		}
	}

	// A pre-v24 users table still carries the legacy `owner` column.
	if !columnNames(x, "users")["owner"] {
		var n int
		if err := x.QueryRow("SELECT COUNT(*) FROM users").Scan(&n); err != nil {
			return err
		}
		if n == 0 {
			name := strings.TrimSpace(envDefault("DEFAULT_USER", "user1"))
			if name == "" {
				name = "user1"
			}
			var dup int
			if err := x.QueryRow("SELECT COUNT(*) FROM users WHERE name = ?", name).Scan(&dup); err != nil {
				return err
			}
			if dup == 0 {
				days := 30
				var d sql.NullInt64
				if err := x.QueryRow("SELECT default_days FROM settings LIMIT 1").Scan(&d); err == nil && d.Valid {
					days = int(d.Int64)
				}
				if _, err := x.Exec(
					`INSERT INTO users (uuid, name, max_logins, expiry_date, is_active, used)
					 VALUES (?, ?, 1, date('now', ?), 1, 0)`,
					uuid.NewString(), name, fmt.Sprintf("+%d days", days),
				); err != nil {
					return err
				}
				seeded = true
			}
		}
	}
	_ = seeded // audit entry (panel.first_run) is written by the panel, not the runner
	return nil
}

func importOwnerCredential(x execer) error {
	owner := strings.TrimSpace(os.Getenv("ADMIN_USERNAME"))
	if owner == "" {
		return nil
	}
	hash := strings.TrimSpace(strings.Trim(os.Getenv("ADMIN_PASSWORD_HASH"), `"'`))
	if !strings.HasPrefix(hash, "$2") {
		return nil
	}
	var password string
	err := x.QueryRow("SELECT password FROM admins WHERE username = ?", owner).Scan(&password)
	if err == sql.ErrNoRows {
		if columnNames(x, "admins")["is_owner"] {
			_, err = x.Exec("INSERT INTO admins (username, password, is_owner) VALUES (?, ?, 1)", owner, hash)
		} else {
			_, err = x.Exec("INSERT INTO admins (username, password) VALUES (?, ?)", owner, hash)
		}
		return err
	}
	if err != nil {
		return err
	}
	if password != "" {
		return nil
	}
	_, err = x.Exec("UPDATE admins SET password = ? WHERE username = ?", hash, owner)
	return err
}

// --- numbered steps (steps.py STEPS) ---

type step struct {
	version     int
	description string
	run         func(execer) error
}

var steps = []step{
	{2, "encrypt node API keys at rest", noopStep},
	{3, "drop orphan daily traffic rows", dropOrphanDailyRows},
	{4, "add lookup indices", addLookupIndices},
	{5, "add admin disabled flag", noopStep},
	{6, "add Telegram notification flags", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		if err := addColumn(x, "settings", "notify_expiry", "BOOLEAN DEFAULT 1 NOT NULL"); err != nil {
			return err
		}
		return addColumn(x, "settings", "notify_traffic", "BOOLEAN DEFAULT 1 NOT NULL")
	}},
	{7, "add automatic backup settings", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		for _, c := range []mcolumn{
			{"auto_backup_enabled", "BOOLEAN DEFAULT 0 NOT NULL"},
			{"auto_backup_time", "VARCHAR DEFAULT '03:30' NOT NULL"},
			{"auto_backup_keep", "INTEGER DEFAULT 50 NOT NULL"},
		} {
			if err := addColumn(x, "settings", c.name, c.add); err != nil {
				return err
			}
		}
		return nil
	}},
	{8, "add user tag column", func(x execer) error {
		if !tableNames(x)["users"] {
			return nil
		}
		return addColumn(x, "users", "tag", "VARCHAR")
	}},
	{9, "add node-down alert flag", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		return addColumn(x, "settings", "notify_node_down", "BOOLEAN DEFAULT 1 NOT NULL")
	}},
	{10, "add offsite backup target", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		return addColumn(x, "settings", "offsite_backup_target", "VARCHAR")
	}},
	{11, "add encrypted Telegram backup setting", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		return addColumn(x, "settings", "telegram_backup_enabled", "BOOLEAN DEFAULT 0 NOT NULL")
	}},
	{12, "seed owner row and first user", seedOwnerAndFirstUser},
	{13, "add per-admin user defaults", noopStep},
	{14, "decrypt stored secrets (at-rest encryption retired)", decryptStoredSecrets},
	{15, "add node server_ca (TLS pinning)", func(x execer) error {
		if !tableNames(x)["nodes"] {
			return nil
		}
		return addColumn(x, "nodes", "server_ca", "VARCHAR")
	}},
	{16, "move the owner credential into the database", importOwnerCredential},
	{17, "add TLS/ACME and Telegram wizard settings", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		for _, c := range []mcolumn{
			{"ssl_cert_file", "VARCHAR"},
			{"ssl_key_file", "VARCHAR"},
			{"acme_domain", "VARCHAR"},
			{"acme_email", "VARCHAR"},
			{"cert_method", "VARCHAR DEFAULT 'selfsigned' NOT NULL"},
			{"panel_url", "VARCHAR"},
			{"bot_owner_setup_complete", "BOOLEAN DEFAULT 0 NOT NULL"},
		} {
			if err := addColumn(x, "settings", c.name, c.add); err != nil {
				return err
			}
		}
		return nil
	}},
	{18, "add panel domain setting", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		return addColumn(x, "settings", "panel_domain", "VARCHAR")
	}},
	{19, "add threshold alert settings", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		for _, c := range []mcolumn{
			{"alert_days_left", "INTEGER DEFAULT 3 NOT NULL"},
			{"alert_usage_enabled", "BOOLEAN DEFAULT 1 NOT NULL"},
			{"alert_usage_pct", "INTEGER DEFAULT 80 NOT NULL"},
			{"alert_cpu_enabled", "BOOLEAN DEFAULT 1 NOT NULL"},
			{"alert_cpu_pct", "INTEGER DEFAULT 85 NOT NULL"},
		} {
			if err := addColumn(x, "settings", c.name, c.add); err != nil {
				return err
			}
		}
		return nil
	}},
	{20, "add subscription profile settings", func(x execer) error {
		if !tableNames(x)["settings"] {
			return nil
		}
		for _, c := range []mcolumn{
			{"sub_profile_title", "VARCHAR DEFAULT 'OVManager VPN' NOT NULL"},
			{"sub_support_url", "VARCHAR DEFAULT '' NOT NULL"},
			{"sub_announce", "VARCHAR DEFAULT '' NOT NULL"},
			{"sub_update_interval_hours", "INTEGER DEFAULT 12 NOT NULL"},
		} {
			if err := addColumn(x, "settings", c.name, c.add); err != nil {
				return err
			}
		}
		return nil
	}},
	{21, "add panel identity (settings.panel_id)", addPanelID},
	{22, "add admin owner flag (admins.is_owner)", addAdminIsOwner},
	{23, "add event delivered markers (delivered)", func(x execer) error {
		_, err := x.Exec(`CREATE TABLE IF NOT EXISTS delivered (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			subscription TEXT NOT NULL,
			event_key TEXT NOT NULL,
			ts REAL NOT NULL,
			UNIQUE (subscription, event_key))`)
		return err
	}},
	{24, "single-admin cut (drop multi-admin columns)", singleAdminSchema},
	{25, "add traffic ledger and settings kv", createTrafficLedgerAndKV},
	{26, "unique owner index (admins.is_owner)", addAdminsOwnerUnique},
}

func noopStep(execer) error { return nil }

func dropOrphanDailyRows(x execer) error {
	if !tableNames(x)["user_traffic_daily"] {
		return nil
	}
	_, err := x.Exec("DELETE FROM user_traffic_daily WHERE user_id NOT IN (SELECT id FROM users)")
	return err
}

func addLookupIndices(x execer) error {
	for _, stmt := range []string{
		"CREATE INDEX IF NOT EXISTS idx_users_expiry ON users(expiry_date)",
		"CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status)",
		"CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)",
	} {
		if _, err := x.Exec(stmt); err != nil {
			return err
		}
	}
	return nil
}

func addPanelID(x execer) error {
	if !tableNames(x)["settings"] {
		return nil
	}
	if err := addColumn(x, "settings", "panel_id", "VARCHAR DEFAULT '' NOT NULL"); err != nil {
		return err
	}
	rows, err := x.Query("SELECT id FROM settings WHERE panel_id IS NULL OR panel_id = ''")
	if err != nil {
		return err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, id := range ids {
		if _, err := x.Exec("UPDATE settings SET panel_id = ? WHERE id = ?", uuid.NewString(), id); err != nil {
			return err
		}
	}
	return nil
}

func addAdminIsOwner(x execer) error {
	if !tableNames(x)["admins"] {
		return nil
	}
	if err := addColumn(x, "admins", "is_owner", "BOOLEAN DEFAULT 0 NOT NULL"); err != nil {
		return err
	}
	owner := strings.TrimSpace(os.Getenv("ADMIN_USERNAME"))
	if owner != "" {
		if _, err := x.Exec("UPDATE admins SET is_owner = 1 WHERE username = ? AND is_owner = 0", owner); err != nil {
			return err
		}
	}
	return nil
}

func singleAdminSchema(x execer) error {
	if tableNames(x)["admins"] {
		if err := addColumn(x, "admins", "is_owner", "INTEGER NOT NULL DEFAULT 0"); err != nil {
			return err
		}
		owner := strings.TrimSpace(os.Getenv("ADMIN_USERNAME"))
		if owner != "" {
			if _, err := x.Exec("UPDATE admins SET is_owner = 1 WHERE username = ? AND is_owner = 0", owner); err != nil {
				return err
			}
		}
		for _, name := range []string{"username_prefix", "disabled", "default_days", "default_traffic_gb", "default_max_users"} {
			if columnNames(x, "admins")[name] {
				if _, err := x.Exec("ALTER TABLE admins DROP COLUMN " + name); err != nil {
					return err
				}
			}
		}
	}
	if tableNames(x)["users"] && columnNames(x, "users")["owner"] {
		if _, err := x.Exec("DROP INDEX IF EXISTS idx_users_owner"); err != nil {
			return err
		}
		if _, err := x.Exec("ALTER TABLE users DROP COLUMN owner"); err != nil {
			return err
		}
	}
	return nil
}

func createTrafficLedgerAndKV(x execer) error {
	if err := createExtraTables(x); err != nil {
		return err
	}
	if !tableNames(x)["user_traffic_daily"] {
		return nil
	}
	_, err := x.Exec(
		"INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes, meta_json) " +
			"SELECT user_id, CAST(strftime('%s', day || 'T00:00:00Z') AS REAL), '', 'backfill', bytes, '{}' " +
			"FROM user_traffic_daily")
	return err
}

func addAdminsOwnerUnique(x execer) error {
	if !tableNames(x)["admins"] {
		return nil
	}
	if _, err := x.Exec(
		"UPDATE admins SET is_owner = 0 WHERE is_owner = 1 AND id NOT IN (SELECT MIN(id) FROM admins WHERE is_owner = 1)",
	); err != nil {
		return err
	}
	_, err := x.Exec("CREATE UNIQUE INDEX IF NOT EXISTS uq_admins_owner ON admins (is_owner) WHERE is_owner = 1")
	return err
}

// --- v14 cryptography (at-rest encryption retired; decrypt legacy rows once) ---

// decryptStoredSecrets reads the retired BOT/NODE_ENCRYPT_KEY values from the
// environment and decrypts any remaining ``enc:`` rows. A row that fails to
// decrypt is left as-is — fail-closed, never truncated.
func decryptStoredSecrets(x execer) error {
	botKey := cleanKey(os.Getenv("BOT_ENCRYPT_KEY"))
	if botKey != "" && tableNames(x)["settings"] {
		var stored sql.NullString
		if err := x.QueryRow("SELECT bot_token FROM settings LIMIT 1").Scan(&stored); err == nil &&
			stored.Valid && strings.HasPrefix(stored.String, "enc:") {
			if plain, err := fernetDecrypt(botKey, stored.String[4:]); err == nil {
				if _, err := x.Exec("UPDATE settings SET bot_token = ?", plain); err != nil {
					return err
				}
			}
		}
	}

	nodeKey := cleanKey(os.Getenv("NODE_ENCRYPT_KEY"))
	if nodeKey == "" {
		nodeKey = botKey
	}
	if nodeKey == "" || !tableNames(x)["nodes"] {
		return nil
	}
	rows, err := x.Query("SELECT id, key FROM nodes")
	if err != nil {
		return err
	}
	type kv struct {
		id  int64
		key string
	}
	var todo []kv
	for rows.Next() {
		var id int64
		var key sql.NullString
		if err := rows.Scan(&id, &key); err != nil {
			rows.Close()
			return err
		}
		if key.Valid && strings.HasPrefix(key.String, "enc:") {
			todo = append(todo, kv{id, key.String})
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, r := range todo {
		plain, err := fernetDecrypt(nodeKey, r.key[4:])
		if err != nil {
			continue // left as-is; re-enter the key
		}
		if _, err := x.Exec("UPDATE nodes SET key = ? WHERE id = ?", plain, r.id); err != nil {
			return err
		}
	}
	return nil
}

func cleanKey(raw string) string {
	return strings.TrimSpace(strings.Trim(raw, `"'`))
}

// fernetDecrypt opens a Fernet token (AES-128-CBC + HMAC-SHA256) with stdlib
// crypto only — no new module. Layout: version|ts(8)|iv(16)|ct|hmac(32); the
// 32-byte key splits into a 16-byte signing half and a 16-byte cipher half.
func fernetDecrypt(keyB64, tokenB64 string) (string, error) {
	rawKey, err := base64.URLEncoding.DecodeString(keyB64)
	if err != nil || len(rawKey) != 32 {
		return "", fmt.Errorf("invalid Fernet key")
	}
	tok, err := base64.URLEncoding.DecodeString(tokenB64)
	if err != nil {
		return "", fmt.Errorf("invalid token encoding: %w", err)
	}
	if len(tok) < 1+8+16+32 || tok[0] != 0x80 {
		return "", fmt.Errorf("invalid Fernet token")
	}
	mac := hmac.New(sha256.New, rawKey[:16])
	mac.Write(tok[:len(tok)-32])
	if !hmac.Equal(mac.Sum(nil), tok[len(tok)-32:]) {
		return "", fmt.Errorf("Fernet HMAC mismatch")
	}
	block, err := aes.NewCipher(rawKey[16:])
	if err != nil {
		return "", err
	}
	ct := tok[25 : len(tok)-32]
	if len(ct) == 0 || len(ct)%aes.BlockSize != 0 {
		return "", fmt.Errorf("invalid Fernet ciphertext")
	}
	out := make([]byte, len(ct))
	cipher.NewCBCDecrypter(block, tok[9:25]).CryptBlocks(out, ct)
	pad := int(out[len(out)-1])
	if pad < 1 || pad > aes.BlockSize || pad > len(out) {
		return "", fmt.Errorf("invalid Fernet padding")
	}
	return string(out[:len(out)-pad]), nil
}

func envDefault(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}
