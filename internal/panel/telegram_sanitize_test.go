// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"database/sql"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

func TestSanitizeTelegramBackupRedactsSecrets(t *testing.T) {
	tmpDir := t.TempDir()
	dbPath := filepath.Join(tmpDir, "test-backup.db")

	d, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatal(err)
	}

	_, err = d.Exec(`
		CREATE TABLE sessions (id INTEGER PRIMARY KEY, token TEXT);
		CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_token TEXT);
		CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT, key TEXT);

		INSERT INTO sessions (token) VALUES ('active-session-token-hash');
		INSERT INTO settings (id, bot_token) VALUES (1, '123456:secret-telegram-token');
		INSERT INTO nodes (id, name, key) VALUES (1, 'node-1', 'node-secret-api-key');
	`)
	if err != nil {
		t.Fatal(err)
	}
	_ = d.Close()

	sanitizedPath, err := sanitizeTelegramBackup(dbPath)
	if err != nil {
		t.Fatalf("sanitizeTelegramBackup failed: %v", err)
	}
	defer func() { _ = d.Close() }()

	// Verify that sanitized backup contains NO usable secrets
	sdb, err := sql.Open("sqlite", sanitizedPath)
	if err != nil {
		t.Fatal(err)
	}
	defer sdb.Close()

	var sessionCount int
	if err := sdb.QueryRow("SELECT COUNT(*) FROM sessions").Scan(&sessionCount); err != nil {
		t.Fatal(err)
	}
	if sessionCount != 0 {
		t.Fatalf("expected 0 sessions in sanitized backup, got %d", sessionCount)
	}

	var botToken string
	if err := sdb.QueryRow("SELECT bot_token FROM settings WHERE id = 1").Scan(&botToken); err != nil {
		t.Fatal(err)
	}
	if botToken != "" {
		t.Fatalf("expected empty bot_token in sanitized backup, got %q", botToken)
	}

	var nodeKey string
	if err := sdb.QueryRow("SELECT key FROM nodes WHERE id = 1").Scan(&nodeKey); err != nil {
		t.Fatal(err)
	}
	if nodeKey == "node-secret-api-key" {
		t.Fatalf("SECURITY FLAW: plaintext node key remained in sanitized backup!")
	}
}
