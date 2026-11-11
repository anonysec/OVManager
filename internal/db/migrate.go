// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT
//
// Schema application: one baseline file plus forward-only SQL migrations.
//
// 2.0.0 is the first supported release, so there is no upgrade path from
// older builds. A database that is not the 2.0.0 baseline is refused rather
// than migrated: guessing at a half-known schema is how data disappears.
package db

import (
	"database/sql"
	"embed"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"

	"github.com/google/uuid"
)

// SchemaVersion is the version stamped into PRAGMA user_version.
// 1 = the 2.0.0 baseline. Every future change adds a migration file.
const SchemaVersion = 1

//go:embed schema.sql
var baseline string

//go:embed migrations
var migrations embed.FS

// execer is the slice of *sql.DB the runner uses; *sql.Tx satisfies it too.
type execer interface {
	Exec(query string, args ...any) (sql.Result, error)
	Query(query string, args ...any) (*sql.Rows, error)
	QueryRow(query string, args ...any) *sql.Row
}

// Migrate brings the database to SchemaVersion.
//
// An empty database receives the baseline; a database already at
// SchemaVersion is left alone apart from idempotent seed rows. Anything else
// is an unsupported build and returns an error the caller must show.
func Migrate(conn *sql.DB) (int, error) {
	tables := tableNames(conn)
	version, err := userVersion(conn)
	if err != nil {
		return 0, err
	}

	switch {
	case len(tables) == 0:
		if err := applyBaseline(conn); err != nil {
			return 0, err
		}
		version = SchemaVersion
	case version == 0:
		return 0, fmt.Errorf("this database was created by a pre-2.0.0 build and cannot be upgraded; move it aside and start with an empty data directory")
	case version > SchemaVersion:
		return version, fmt.Errorf("database schema version %d is newer than this build supports (%d); update the panel or restore an older database", version, SchemaVersion)
	}

	if err := seedSettings(conn); err != nil {
		return version, err
	}
	if err := seedOwnerAndFirstUser(conn); err != nil {
		return version, err
	}
	applied, err := applyMigrations(conn, version)
	if err != nil {
		return version, err
	}
	return applied, nil
}

func applyBaseline(conn *sql.DB) error {
	tx, err := conn.Begin()
	if err != nil {
		return err
	}
	if _, err := tx.Exec(baseline); err != nil {
		_ = tx.Rollback()
		return fmt.Errorf("apply the 2.0.0 schema baseline: %w", err)
	}
	if err := stamp(tx, SchemaVersion); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

// applyMigrations runs migrations/NNN_*.sql in numeric order, skipping
// versions at or below current. Each file and its version stamp commit
// together, so a failed migration leaves the previous version intact.
func applyMigrations(conn *sql.DB, current int) (int, error) {
	entries, err := migrations.ReadDir("migrations")
	if err != nil {
		return current, err
	}
	type migration struct {
		version int
		name    string
	}
	var pending []migration
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".sql") {
			continue
		}
		prefix, _, ok := strings.Cut(e.Name(), "_")
		if !ok {
			return current, fmt.Errorf("migration %q needs an NNN_name.sql prefix", e.Name())
		}
		n, err := strconv.Atoi(prefix)
		if err != nil {
			return current, fmt.Errorf("migration %q has a non-numeric prefix", e.Name())
		}
		if n > current {
			pending = append(pending, migration{version: n, name: e.Name()})
		}
	}
	sort.Slice(pending, func(i, j int) bool { return pending[i].version < pending[j].version })

	for _, m := range pending {
		body, err := migrations.ReadFile("migrations/" + m.name)
		if err != nil {
			return current, err
		}
		tx, err := conn.Begin()
		if err != nil {
			return current, err
		}
		if _, err := tx.Exec(string(body)); err != nil {
			_ = tx.Rollback()
			return current, fmt.Errorf("migration %s: %w", m.name, err)
		}
		if err := stamp(tx, m.version); err != nil {
			_ = tx.Rollback()
			return current, err
		}
		if err := tx.Commit(); err != nil {
			return current, err
		}
		current = m.version
	}
	return current, nil
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

func envDefault(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func seedSettings(x execer) error {
	var n int
	if err := x.QueryRow("SELECT COUNT(*) FROM Setting").Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	urlpath := strings.Trim(strings.TrimSpace(os.Getenv("BasePath")), `"'`)
	urlpath = strings.Trim(urlpath, "/")
	_, err := x.Exec(
		`INSERT INTO Setting
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
	owner := envDefault("OwnerUsername", "admin")
	if owner != "" {
		var n int
		if err := x.QueryRow("SELECT COUNT(*) FROM Admin WHERE username = ?", owner).Scan(&n); err != nil {
			return err
		}
		if n == 0 {
			if _, err := x.Exec("INSERT INTO Admin (username, password, is_owner) VALUES (?, '', 1)", owner); err != nil {
				return err
			}
		}
	}

	var users int
	if err := x.QueryRow("SELECT COUNT(*) FROM User").Scan(&users); err != nil {
		return err
	}
	if users > 0 {
		return nil
	}
	name := strings.TrimSpace(envDefault("DEFAULT_USER", "user1"))
	if name == "" {
		name = "user1"
	}
	days := 30
	var d sql.NullInt64
	if err := x.QueryRow("SELECT default_days FROM Setting LIMIT 1").Scan(&d); err == nil && d.Valid {
		days = int(d.Int64)
	}
	_, err := x.Exec(
		`INSERT INTO User (uuid, name, max_logins, expiry_date, is_active, used)
		 VALUES (?, ?, 1, date('now', ?), 1, 0)`,
		uuid.NewString(), name, fmt.Sprintf("+%d days", days),
	)
	return err
}
