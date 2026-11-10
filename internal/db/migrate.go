// Schema migration runner: numbered steps applied in order with guards
// so a database is upgraded exactly like the legacy runner did.
// The version lives in PRAGMA user_version (no schema_version table).

package db

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/google/uuid"
)

// SchemaVersion is the HEAD schema version (constants.SCHEMA_VERSION).
const SchemaVersion = 35

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
		if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS user_node_usage (user_id INTEGER NOT NULL, node_id INTEGER NOT NULL, baseline INTEGER NOT NULL, epoch TEXT NOT NULL DEFAULT '', PRIMARY KEY (user_id, node_id))`); err != nil {
			return 0, err
		}
		if err := createExtraTables(conn); err != nil {
			return 0, err
		}
		if _, err := reconcileColumns(conn); err != nil {
			return 0, err
		}
		if err := createMappedIndices(conn); err != nil {
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
		// No indices here: uq_admins_owner must come after step 26 dedupes
		// the owner rows an older database can hold. The step loop below
		// creates them.
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

	// Converge on the mapped schema on every upgrade path too, so a database
	// that predates a mapped table (e.g. a legacy DB with no sessions table)
	// gets it. Tables first, then reconcile adds missing columns.
	//
	// The indices are created AFTER the step loop, not here: uq_admins_owner
	// is a UNIQUE index, and step 26 is what dedupes the multiple is_owner
	// rows an older database can hold. Creating the index first would make
	// such an upgrade fail with a UNIQUE constraint error instead of
	// deduping.
	if err := createMappedTables(conn); err != nil {
		return before, err
	}
	if _, err := reconcileColumns(conn); err != nil {
		return before, err
	}

	for _, s := range steps {
		if s.version <= before {
			continue
		}
		tx, err := conn.Begin()
		if err != nil {
			return before, err
		}
		if err := s.run(tx); err != nil {
			_ = tx.Rollback()
			return before, fmt.Errorf("migration v%d (%s): %w", s.version, s.description, err)
		}
		if err := stamp(tx, s.version); err != nil {
			_ = tx.Rollback()
			return before, err
		}
		if err := tx.Commit(); err != nil {
			return before, err
		}
		before = s.version
	}

	// The mapped indices land on every path, after the steps that may have
	// to dedupe the rows they constrain.
	if err := createMappedIndices(conn); err != nil {
		return before, err
	}

	if err := createExtraTables(conn); err != nil {
		return 0, err
	}
	if err := seedSettings(conn); err != nil {
		return 0, err
	}
	return SchemaVersion, nil
}

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

type mcolumn struct {
	name string
	add  string // "TYPE [DEFAULT x] [NOT NULL]"
}

// mappedTableOrder is create_all's (dependency-free) table set.
var mappedTableOrder = []string{"admins", "sessions", "users", "nodes", "settings"}

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
		{"data_limit", "BIGINT DEFAULT 0 NOT NULL"},
		{"traffic_reset", "VARCHAR DEFAULT 'never' NOT NULL"},
		{"last_traffic_reset", "BIGINT DEFAULT 0 NOT NULL"},
		{"max_logins", "INTEGER DEFAULT 1 NOT NULL"},
		{"expiry_date", "DATE DEFAULT CURRENT_TIMESTAMP NOT NULL"},
		{"is_active", "BOOLEAN DEFAULT 1 NOT NULL"},
		{"last_online", "DATETIME"},
		{"tag", "VARCHAR"},
		{"telegram_chat_id", "INTEGER"},
		{"activation_token_hash", "VARCHAR(64)"},
		{"activation_token_expires_at", "REAL"},
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
		{"extra_ports", "VARCHAR DEFAULT '' NOT NULL"},
		{"node_contract_version", "INTEGER DEFAULT 0 NOT NULL"},
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
		{"telegram_summary_time", "VARCHAR DEFAULT '09:00' NOT NULL"},
		{"ssl_cert_file", "VARCHAR"},
		{"ssl_key_file", "VARCHAR"},
		{"acme_domain", "VARCHAR"},
		{"acme_email", "VARCHAR"},
		{"cert_method", "VARCHAR DEFAULT 'selfsigned' NOT NULL"},
		{"panel_id", "VARCHAR DEFAULT '' NOT NULL"},
		{"panel_url", "VARCHAR"},
		{"panel_domain", "VARCHAR"},
		{"bot_owner_setup_complete", "BOOLEAN DEFAULT 0 NOT NULL"},
		{"backup_last_success_day", "VARCHAR"},
		{"telegram_sent_day", "VARCHAR"},
		{"snapshot_max_nodes", "INTEGER DEFAULT 0 NOT NULL"},
		{"telegram_last_update_id", "BIGINT DEFAULT 0 NOT NULL"},
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
	"CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions (token_hash)",
	"CREATE UNIQUE INDEX IF NOT EXISTS uq_users_activation_token_hash ON users (activation_token_hash) WHERE activation_token_hash IS NOT NULL AND activation_token_hash <> ''",
	"CREATE INDEX IF NOT EXISTS idx_users_expiry ON users(expiry_date)",
	"CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status)",
	"CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)",
}

func createMappedTables(x execer) error {
	for _, table := range mappedTableOrder {
		if _, err := x.Exec(createTableSQL(table)); err != nil {
			return err
		}
	}
	return nil
}

func createMappedIndices(x execer) error {
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
		def := c.name + " " + c.add
		// users.id must be AUTOINCREMENT so deleted highest IDs are not reused.
		if table == "users" && c.name == "id" {
			def = "id INTEGER PRIMARY KEY AUTOINCREMENT"
		}
		parts = append(parts, def)
	}
	if table != "users" {
		parts = append(parts, "PRIMARY KEY (id)")
	}
	for _, u := range mappedUniques[table] {
		parts = append(parts, "UNIQUE ("+u+")")
	}
	return "CREATE TABLE IF NOT EXISTS " + table + " (\n  " + strings.Join(parts, ",\n  ") + "\n)"
}

// extraTables is constants._EXTRA_DDL: the non-ORM tables.
var extraTables = []string{
	`CREATE TABLE IF NOT EXISTS delivered (id INTEGER PRIMARY KEY AUTOINCREMENT, subscription TEXT NOT NULL, event_key TEXT NOT NULL, ts REAL NOT NULL, UNIQUE (subscription, event_key))`,
	`CREATE TABLE IF NOT EXISTS user_traffic_daily (user_id INTEGER NOT NULL, day TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, day))`,
	`CREATE TABLE IF NOT EXISTS traffic_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user_id INTEGER NOT NULL, node_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, delta_bytes INTEGER NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}', UNIQUE (user_id, ts, kind, node_id))`,
	`CREATE TABLE IF NOT EXISTS pending_user_revocations (node_id INTEGER NOT NULL, user_id INTEGER NOT NULL, user_uuid TEXT NOT NULL, user_name TEXT NOT NULL, created_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '', PRIMARY KEY (node_id, user_id))`,
	`CREATE TABLE IF NOT EXISTS NodeUsage (id INTEGER PRIMARY KEY AUTOINCREMENT, node_id INTEGER NOT NULL, created_at REAL NOT NULL, uplink INTEGER NOT NULL DEFAULT 0, downlink INTEGER NOT NULL DEFAULT 0, UNIQUE (created_at, node_id))`,
	`CREATE INDEX IF NOT EXISTS idx_node_usage_created ON NodeUsage(created_at)`,
	`CREATE TABLE IF NOT EXISTS NodeUsageResetLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, node_id INTEGER NOT NULL, created_at REAL NOT NULL, uplink INTEGER NOT NULL, downlink INTEGER NOT NULL)`,
	`CREATE INDEX IF NOT EXISTS idx_node_usage_reset_node ON NodeUsageResetLogs(node_id, created_at)`,
	`CREATE TABLE IF NOT EXISTS UserUsageResetLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at REAL NOT NULL, used_bytes INTEGER NOT NULL)`,
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
	// Ensure audit_logs.promoted column exists (for promoteEvents optimization).
	if present["audit_logs"] {
		if !columnNames(x, "audit_logs")["promoted"] {
			if _, err := x.Exec(`ALTER TABLE audit_logs ADD COLUMN promoted BOOLEAN NOT NULL DEFAULT 0`); err != nil {
				return added, err
			}
			added = append(added, "audit_logs.promoted")
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

// --- first-run seeds (seeds) ---

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
	{27, "encrypt stored secrets at rest", encryptStoredSecrets},
	{28, "delete non-owner sessions", deleteNonOwnerSessions},
	{29, "pending user revocations and monotonic users.id", rebuildUsersWithAutoincrement},
	{30, "nodes.node_contract_version", func(x execer) error {
		if !tableNames(x)["nodes"] {
			return nil
		}
		return addColumn(x, "nodes", "node_contract_version", "INTEGER DEFAULT 0 NOT NULL")
	}},
	{31, "deleted_nodes undo snapshot", func(x execer) error {
		if _, err := x.Exec(`CREATE TABLE IF NOT EXISTS deleted_nodes (id INTEGER PRIMARY KEY, snap_json TEXT NOT NULL, deleted_at REAL NOT NULL, expires_at REAL NOT NULL)`); err != nil {
			return err
		}
		_, err := x.Exec(`CREATE INDEX IF NOT EXISTS idx_deleted_nodes_expires ON deleted_nodes(expires_at)`)
		return err
	}},
	{32, "users.telegram_chat_id (Telegram management bot binding)", func(x execer) error {
		if !tableNames(x)["users"] {
			return nil
		}
		return addColumn(x, "users", "telegram_chat_id", "INTEGER")
	}},
	{33, "users.activation_token_hash + activation_token_expires_at (Telegram activation token)", func(x execer) error {
		if !tableNames(x)["users"] {
			return nil
		}
		if err := addColumn(x, "users", "activation_token_hash", "VARCHAR(64)"); err != nil {
			return err
		}
		if err := addColumn(x, "users", "activation_token_expires_at", "REAL"); err != nil {
			return err
		}
		_, err := x.Exec(`CREATE UNIQUE INDEX IF NOT EXISTS uq_users_activation_token_hash ON users(activation_token_hash) WHERE activation_token_hash IS NOT NULL AND activation_token_hash <> ''`)
		return err
	}},
	{34, "user_node_usage baselines table", func(x execer) error {
		if !tableNames(x)["users"] {
			return nil
		}
		if _, err := x.Exec(`CREATE TABLE IF NOT EXISTS user_node_usage (user_id INTEGER NOT NULL, node_id INTEGER NOT NULL, baseline INTEGER NOT NULL, epoch TEXT NOT NULL DEFAULT '', PRIMARY KEY (user_id, node_id))`); err != nil {
			return err
		}
		rows, err := x.Query(`SELECT id, COALESCE(node_usage,'{}') FROM users`)
		if err != nil {
			return nil
		}
		defer rows.Close()
		type row struct {
			id    int64
			state string
		}
		var pending []row
		for rows.Next() {
			var r row
			if rows.Scan(&r.id, &r.state) == nil && r.state != "" && r.state != "{}" {
				pending = append(pending, r)
			}
		}
		for _, r := range pending {
			m := map[string]any{}
			if json.Unmarshal([]byte(r.state), &m) != nil {
				continue
			}
			for k, v := range m {
				if k == "push_hash" || k == "__reseed" || k == "__epochs" {
					continue
				}
				nid, err := strconv.ParseInt(k, 10, 64)
				if err != nil {
					continue
				}
				base := int64(0)
				if f, ok := v.(float64); ok {
					base = int64(f)
				} else if iv, ok := v.(int64); ok {
					base = iv
				}
				_, _ = x.Exec(`INSERT OR IGNORE INTO user_node_usage (user_id, node_id, baseline) VALUES (?, ?, ?)`, r.id, nid, base)
			}
		}
		return nil
	}},
	{35, "drop legacy snapshot/audit/traffic tables (DB simplification)", func(x execer) error {
		for _, t := range []string{
			"node_health_snapshots", "traffic_snapshots", "security_snapshots",
			"audit_logs", "deleted_users", "deleted_nodes", "login_attempts", "settings_kv",
		} {
			_, _ = x.Exec("DROP TABLE IF EXISTS " + t)
		}
		return nil
	}},
}
