package cli

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/go/internal/crypto"
	"github.com/anonysec/OVManager/go/internal/db"
	_ "modernc.org/sqlite"
)

func TestRestoreEncryptedBackupRoundTrip(t *testing.T) {
	dir := t.TempDir()
	installDir := filepath.Join(dir, "opt")
	if err := os.MkdirAll(installDir, 0o755); err != nil {
		t.Fatal(err)
	}
	backupDir := filepath.Join(dir, "backups")
	if err := os.MkdirAll(backupDir, 0o700); err != nil {
		t.Fatal(err)
	}
	dbPath := filepath.Join(dir, "ovmanager.db")
	conn, err := db.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`CREATE TABLE t (v TEXT); INSERT INTO t VALUES ('secret-data');`); err != nil {
		t.Fatal(err)
	}
	_ = conn.Close()

	// create encrypted backup
	srcBackup := filepath.Join(backupDir, "ovmanager-backup.db")
	if err := copyFile(dbPath, srcBackup); err != nil {
		t.Fatal(err)
	}
	encBackup := filepath.Join(backupDir, "ovmanager-backup.db.enc")
	key, err := crypto.GetOrCreateSecretKey(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := crypto.EncryptFile(srcBackup, encBackup, key); err != nil {
		t.Fatal(err)
	}

	install := Install{InstallDir: installDir, DataDir: dir}
	text, code := runRestore(install, "ovmanager-backup.db.enc")
	if code != 0 {
		t.Fatalf("runRestore failed: %s", text)
	}
	// verify restored db content
	conn2, err := db.Open(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer conn2.Close()
	var v string
	if err := conn2.QueryRow("SELECT v FROM t").Scan(&v); err != nil {
		t.Fatal(err)
	}
	if v != "secret-data" {
		t.Fatalf("restored value = %q", v)
	}
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0o600)
}
