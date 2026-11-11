package db

import (
	"database/sql"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/crypto"
	_ "modernc.org/sqlite"
)

func TestMigrateEncryptsStoredSecrets(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)

	conn, err := sql.Open("sqlite", filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE Setting (id INTEGER PRIMARY KEY, bot_token TEXT); CREATE TABLE Node (id INTEGER PRIMARY KEY, key TEXT);`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO Setting (id, bot_token) VALUES (1, 'plain-bot-token'); INSERT INTO Node (id, key) VALUES (1, 'plain-node-key');`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec("PRAGMA user_version = 26"); err != nil {
		t.Fatal(err)
	}

	if _, err := Migrate(conn); err != nil {
		t.Fatal(err)
	}
	var bot, key string
	if err := conn.QueryRow("SELECT bot_token FROM Setting WHERE id = 1").Scan(&bot); err != nil {
		t.Fatal(err)
	}
	if err := conn.QueryRow("SELECT key FROM Node WHERE id = 1").Scan(&key); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(bot, crypto.EncPrefix) || !strings.HasPrefix(key, crypto.EncPrefix) {
		t.Fatalf("secrets not encrypted: bot=%q key=%q", bot, key)
	}
	// idempotent
	if _, err := Migrate(conn); err != nil {
		t.Fatal(err)
	}
}
