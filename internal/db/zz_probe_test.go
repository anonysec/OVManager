package db

import (
	"database/sql"
	"fmt"
	"os"
	"testing"

	_ "modernc.org/sqlite"
)

func TestZZProbeLegacyUpgrade(t *testing.T) {
	_ = os.Remove("/tmp/probe_legacy.db")
	d, err := sql.Open("sqlite", "/tmp/probe_legacy.db")
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	// A v2.0.3-shaped database: lowercase tables with rows.
	legacy := []string{
		`CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, uuid VARCHAR, name VARCHAR DEFAULT '' NOT NULL, total BIGINT, used BIGINT, last_node_usage BIGINT DEFAULT 0 NOT NULL, node_usage VARCHAR DEFAULT '{}' NOT NULL, max_logins INTEGER DEFAULT 1 NOT NULL, expiry_date DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, is_active BOOLEAN DEFAULT 1 NOT NULL, last_online DATETIME, tag VARCHAR, telegram_chat_id INTEGER, activation_token_hash VARCHAR(64), activation_token_expires_at REAL)`,
		`INSERT INTO users (id, uuid, name, used, total, is_active) VALUES (7, 'uuid-alice', 'alice', 4242, 0, 1)`,
		`CREATE TABLE admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username VARCHAR DEFAULT '' NOT NULL, password VARCHAR DEFAULT '' NOT NULL, is_owner BOOLEAN DEFAULT 0 NOT NULL, telegram_id INTEGER)`,
		`INSERT INTO admins (id, username, password, is_owner) VALUES (1, 'admin', 'hash', 1)`,
		`CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR DEFAULT '' NOT NULL, address VARCHAR DEFAULT '' NOT NULL, tunnel_address VARCHAR, protocol VARCHAR DEFAULT '' NOT NULL, ovpn_port INTEGER DEFAULT 0 NOT NULL, port INTEGER DEFAULT 2083 NOT NULL, key VARCHAR DEFAULT '' NOT NULL, status BOOLEAN DEFAULT 1 NOT NULL, server_ca VARCHAR, country_code VARCHAR, latitude FLOAT, longitude FLOAT, extra_ports VARCHAR DEFAULT '' NOT NULL, node_contract_version INTEGER DEFAULT 0 NOT NULL)`,
		`INSERT INTO nodes (id, name, address, key) VALUES (3, 'node1', '1.2.3.4', 'k')`,
		`CREATE TABLE settings (id INTEGER PRIMARY KEY AUTOINCREMENT, tunnel_address VARCHAR, port INTEGER DEFAULT 1194 NOT NULL, protocol VARCHAR DEFAULT 'tcp' NOT NULL, timezone VARCHAR DEFAULT 'UTC' NOT NULL, bot_token VARCHAR, bot_enabled BOOLEAN DEFAULT 0 NOT NULL, default_days INTEGER DEFAULT 30 NOT NULL, default_traffic_gb INTEGER DEFAULT 100 NOT NULL, default_max_users INTEGER DEFAULT 1 NOT NULL, owner_telegram_id INTEGER, notify_expiry BOOLEAN DEFAULT 1 NOT NULL, notify_traffic BOOLEAN DEFAULT 1 NOT NULL, notify_node_down BOOLEAN DEFAULT 1 NOT NULL)`,
		`INSERT INTO settings (id, bot_token) VALUES (1, 'tok')`,
		`CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash VARCHAR DEFAULT '' NOT NULL, username VARCHAR DEFAULT '' NOT NULL, role VARCHAR DEFAULT '' NOT NULL, created_at FLOAT DEFAULT 0 NOT NULL, expires_at FLOAT DEFAULT 0 NOT NULL, last_seen_at FLOAT DEFAULT 0 NOT NULL, user_agent VARCHAR, ip VARCHAR)`,
		`CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT)`,
		`CREATE TABLE traffic_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, total_used REAL NOT NULL, active_connections INTEGER NOT NULL, online_users INTEGER NOT NULL, active_users INTEGER NOT NULL, total_users INTEGER NOT NULL)`,
	}
	for _, s := range legacy {
		if _, err := d.Exec(s); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}
	if _, err := d.Exec(`PRAGMA user_version = 26`); err != nil {
		t.Fatal(err)
	}

	v, err := Migrate(d)
	if err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	fmt.Println("schema version:", v)

	tables := []string{}
	rows, _ := d.Query(`SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name`)
	for rows.Next() {
		var n string
		rows.Scan(&n)
		tables = append(tables, n)
	}
	rows.Close()
	fmt.Println("tables:", tables)

	for _, t := range []string{"User", "Admin", "Node", "Setting", "users", "admins", "nodes", "settings"} {
		var n int
		if err := d.QueryRow(`SELECT COUNT(*) FROM ` + t).Scan(&n); err != nil {
			fmt.Printf("%-10s ERROR %v\n", t, err)
			continue
		}
		fmt.Printf("%-10s rows=%d\n", t, n)
	}
	var name string
	_ = d.QueryRow(`SELECT name FROM User LIMIT 1`).Scan(&name)
	fmt.Println("first User name:", name)
}
