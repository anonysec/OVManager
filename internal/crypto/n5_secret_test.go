package crypto

import (
	"database/sql"
	"os"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

func TestGetOrCreateSecretKeyRefusesMissingKeyWithEncryptedData(t *testing.T) {
	dir := t.TempDir()
	conn, err := sql.Open("sqlite", filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE Node (id INTEGER PRIMARY KEY, key TEXT, settings TEXT DEFAULT '{}'); INSERT INTO Node (id, key) VALUES (1, 'enc:v2:AAAA');`); err != nil {
		t.Fatal(err)
	}
	if _, err := GetOrCreateSecretKey(dir); err == nil {
		t.Fatal("expected error when secret.key is missing but DB has encrypted values")
	}
}

func TestGetOrCreateSecretKeyRefusesCorruptKeyWithEncryptedData(t *testing.T) {
	dir := t.TempDir()
	conn, err := sql.Open("sqlite", filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE Setting (id INTEGER PRIMARY KEY, bot_token TEXT); INSERT INTO Setting (id, bot_token) VALUES (1, 'enc:v2:AAAA');`); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "secret.key"), []byte("not-a-key\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := GetOrCreateSecretKey(dir); err == nil {
		t.Fatal("expected error when secret.key is corrupt and DB has encrypted values")
	}
}

func TestGetOrCreateSecretKeyGeneratesWhenNoEncryptedData(t *testing.T) {
	dir := t.TempDir()
	key, err := GetOrCreateSecretKey(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(key) != 32 {
		t.Fatalf("key len = %d", len(key))
	}
}
