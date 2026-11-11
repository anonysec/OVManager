package db

import (
	"database/sql"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func openTemp(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return conn
}

func columns(t *testing.T, conn *sql.DB, table string) []string {
	t.Helper()
	rows, err := conn.Query("PRAGMA table_info(" + table + ")")
	if err != nil {
		t.Fatalf("table_info %s: %v", table, err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var (
			cid, notnull, pk int
			name, ctype      string
			dflt             sql.NullString
		)
		if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt, &pk); err != nil {
			t.Fatal(err)
		}
		out = append(out, name)
	}
	return out
}

func TestFreshDatabaseIsTheBaseline(t *testing.T) {
	conn := openTemp(t)
	version, err := Migrate(conn)
	if err != nil {
		t.Fatalf("migrate: %v", err)
	}
	if version != SchemaVersion {
		t.Fatalf("version = %d, want %d", version, SchemaVersion)
	}
	var stamped int
	if err := conn.QueryRow("PRAGMA user_version").Scan(&stamped); err != nil {
		t.Fatal(err)
	}
	if stamped != SchemaVersion {
		t.Fatalf("user_version = %d, want %d", stamped, SchemaVersion)
	}

	want := map[string][]string{
		"Admin":                 {"id", "username", "password", "is_owner", "role", "telegram_id"},
		"User":                  {"id", "uuid", "name", "total", "used", "last_node_usage", "node_usage", "max_logins", "expiry_date", "is_active", "last_online", "tag", "telegram_chat_id", "activation_token_hash", "activation_token_expires_at"},
		"Node":                  {"id", "name", "address", "tunnel_address", "protocol", "ovpn_port", "port", "key", "status", "server_ca", "country_code", "latitude", "longitude", "extra_ports", "node_contract_version", "settings"},
		"Delivered":             {"id", "subscription", "event_key", "ts"},
		"NodeStat":              {"id", "node_id", "created_at", "cpu", "memory", "live_count", "reachable"},
		"PendingUserRevocation": {"node_id", "user_id", "user_uuid", "user_name", "created_at", "last_error"},
		"TrafficStat":           {"ts", "total_used", "active_connections"},
		"UserNodeUsage":         {"user_id", "node_id", "baseline", "epoch"},
		"UserTrafficDaily":      {"user_id", "day", "bytes"},
	}
	tables := tableNames(conn)
	for table, wantCols := range want {
		if !tables[table] {
			t.Errorf("table %s is missing", table)
			continue
		}
		got := columns(t, conn, table)
		sort.Strings(got)
		sorted := append([]string(nil), wantCols...)
		sort.Strings(sorted)
		if len(got) != len(sorted) {
			t.Errorf("%s columns = %v, want %v", table, got, sorted)
			continue
		}
		for i := range got {
			if got[i] != sorted[i] {
				t.Errorf("%s columns = %v, want %v", table, got, sorted)
				break
			}
		}
	}
	if !tables["Setting"] {
		t.Error("table Setting is missing")
	}

	var settings int
	if err := conn.QueryRow("SELECT COUNT(*) FROM Setting").Scan(&settings); err != nil {
		t.Fatal(err)
	}
	if settings != 1 {
		t.Errorf("Setting rows = %d, want 1", settings)
	}
	var owner string
	if err := conn.QueryRow("SELECT username FROM Admin WHERE is_owner = 1").Scan(&owner); err != nil {
		t.Fatalf("no owner row: %v", err)
	}
}

func TestSecondMigrateIsIdempotent(t *testing.T) {
	conn := openTemp(t)
	if _, err := Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := Migrate(conn); err != nil {
		t.Fatalf("second migrate: %v", err)
	}
	var settings int
	if err := conn.QueryRow("SELECT COUNT(*) FROM Setting").Scan(&settings); err != nil {
		t.Fatal(err)
	}
	if settings != 1 {
		t.Errorf("Setting rows after second migrate = %d, want 1", settings)
	}
}

func TestPreResetDatabaseIsRefused(t *testing.T) {
	conn := openTemp(t)
	if _, err := conn.Exec("CREATE TABLE users (id INTEGER)"); err != nil {
		t.Fatal(err)
	}
	if _, err := Migrate(conn); err == nil {
		t.Fatal("pre-2.0.0 database was accepted; it must be refused")
	} else if !strings.Contains(err.Error(), "pre-2.0.0") {
		t.Fatalf("error = %v, want a pre-2.0.0 explanation", err)
	}
}

func TestNewerDatabaseIsRefused(t *testing.T) {
	conn := openTemp(t)
	if _, err := Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 99"); err != nil {
		t.Fatal(err)
	}
	if _, err := Migrate(conn); err == nil {
		t.Fatal("newer database was accepted")
	}
}
