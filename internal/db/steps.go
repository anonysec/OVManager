// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

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

	"github.com/anonysec/OVManager/internal/config"
	ovcrypto "github.com/anonysec/OVManager/internal/crypto"
)

func noopStep(execer) error { return nil }

func dropOrphanDailyRows(x execer) error {
	if !tableNames(x)["UserTrafficDaily"] {
		return nil
	}
	_, err := x.Exec("DELETE FROM UserTrafficDaily WHERE user_id NOT IN (SELECT id FROM User)")
	return err
}

func addLookupIndices(x execer) error {
	for _, stmt := range []string{
		"CREATE INDEX IF NOT EXISTS idx_users_expiry ON User(expiry_date)",
		"CREATE INDEX IF NOT EXISTS idx_nodes_status ON Node(status)",
		"CREATE INDEX IF NOT EXISTS idx_nodes_name ON Node(name)",
	} {
		if _, err := x.Exec(stmt); err != nil {
			return err
		}
	}
	return nil
}

func addPanelID(x execer) error {
	if !tableNames(x)["Setting"] {
		return nil
	}
	if err := addColumn(x, "Setting", "panel_id", "VARCHAR DEFAULT '' NOT NULL"); err != nil {
		return err
	}
	rows, err := x.Query("SELECT id FROM Setting WHERE panel_id IS NULL OR panel_id = ''")
	if err != nil {
		return err
	}
	var ids []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			_ = rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	_ = rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, id := range ids {
		if _, err := x.Exec("UPDATE Setting SET panel_id = ? WHERE id = ?", uuid.NewString(), id); err != nil {
			return err
		}
	}
	return nil
}

func addAdminIsOwner(x execer) error {
	if !tableNames(x)["Admin"] {
		return nil
	}
	if err := addColumn(x, "Admin", "is_owner", "BOOLEAN DEFAULT 0 NOT NULL"); err != nil {
		return err
	}
	owner := strings.TrimSpace(os.Getenv("ADMIN_USERNAME"))
	if owner != "" {
		if _, err := x.Exec("UPDATE Admin SET is_owner = 1 WHERE username = ? AND is_owner = 0", owner); err != nil {
			return err
		}
	}
	return nil
}

func singleAdminSchema(x execer) error {
	if tableNames(x)["Admin"] {
		if err := addColumn(x, "Admin", "is_owner", "INTEGER NOT NULL DEFAULT 0"); err != nil {
			return err
		}
		owner := strings.TrimSpace(os.Getenv("ADMIN_USERNAME"))
		if owner != "" {
			if _, err := x.Exec("UPDATE Admin SET is_owner = 1 WHERE username = ? AND is_owner = 0", owner); err != nil {
				return err
			}
		}
		for _, name := range []string{"username_prefix", "disabled", "default_days", "default_traffic_gb", "default_max_users"} {
			if columnNames(x, "Admin")[name] {
				if _, err := x.Exec("ALTER TABLE Admin DROP COLUMN " + name); err != nil {
					return err
				}
			}
		}
	}
	if tableNames(x)["User"] && columnNames(x, "User")["owner"] {
		if _, err := x.Exec("DROP INDEX IF EXISTS idx_User_owner"); err != nil {
			return err
		}
		if _, err := x.Exec("ALTER TABLE User DROP COLUMN owner"); err != nil {
			return err
		}
	}
	return nil
}

func createTrafficLedgerAndKV(x execer) error {
	if err := createExtraTables(x); err != nil {
		return err
	}
	if !tableNames(x)["UserTrafficDaily"] {
		return nil
	}
	_, err := x.Exec(
		"INSERT OR IGNORE INTO TrafficLedger (user_id, ts, node_id, kind, delta_bytes, meta_json) " +
			"SELECT user_id, CAST(strftime('%s', day || 'T00:00:00Z') AS REAL), '', 'backfill', bytes, '{}' " +
			"FROM UserTrafficDaily")
	return err
}

func addAdminsOwnerUnique(x execer) error {
	if !tableNames(x)["Admin"] {
		return nil
	}
	if _, err := x.Exec(
		"UPDATE Admin SET is_owner = 0 WHERE is_owner = 1 AND id NOT IN (SELECT MIN(id) FROM Admin WHERE is_owner = 1)",
	); err != nil {
		return err
	}
	_, err := x.Exec("CREATE UNIQUE INDEX IF NOT EXISTS uq_admins_owner ON Admin (is_owner) WHERE is_owner = 1")
	return err
}

// --- v14 cryptography (at-rest encryption retired; decrypt legacy rows once) ---

// decryptStoredSecrets reads the retired BOT/NODE_ENCRYPT_KEY values from the
// environment and decrypts any remaining “enc:“ rows. A row that fails to
// decrypt is left as-is — fail-closed, never truncated.
func decryptStoredSecrets(x execer) error {
	botKey := cleanKey(os.Getenv("BOT_ENCRYPT_KEY"))
	if botKey != "" && tableNames(x)["Setting"] {
		var stored sql.NullString
		if err := x.QueryRow("SELECT bot_token FROM Setting LIMIT 1").Scan(&stored); err == nil &&
			stored.Valid && strings.HasPrefix(stored.String, "enc:") {
			if plain, err := fernetDecrypt(botKey, stored.String[4:]); err == nil {
				if _, err := x.Exec("UPDATE Setting SET bot_token = ?", plain); err != nil {
					return err
				}
			}
		}
	}

	nodeKey := cleanKey(os.Getenv("NODE_ENCRYPT_KEY"))
	if nodeKey == "" {
		nodeKey = botKey
	}
	if nodeKey == "" || !tableNames(x)["Node"] {
		return nil
	}
	rows, err := x.Query("SELECT id, key FROM Node")
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
			_ = rows.Close()
			return err
		}
		if key.Valid && strings.HasPrefix(key.String, "enc:") {
			todo = append(todo, kv{id, key.String})
		}
	}
	_ = rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, r := range todo {
		plain, err := fernetDecrypt(nodeKey, r.key[4:])
		if err != nil {
			continue // left as-is; re-enter the key
		}
		if _, err := x.Exec("UPDATE Node SET key = ? WHERE id = ?", plain, r.id); err != nil {
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
		return "", fmt.Errorf("fernet HMAC mismatch")
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

// encryptStoredSecrets encrypts plaintext nodes.key and settings.bot_token values
// that are not already enc:v2:. Idempotent and transactional: any failure
// aborts the migration so no partial state is stamped.
func encryptStoredSecrets(x execer) error {
	dataDir := config.EnvOrFile("DATA_DIR", "data")

	if tableNames(x)["Setting"] && columnNames(x, "Setting")["bot_token"] {
		rows, err := x.Query("SELECT rowid, bot_token FROM Setting")
		if err != nil {
			return err
		}
		type row struct {
			rowid int64
			value string
		}
		var todo []row
		for rows.Next() {
			var rowid int64
			var value sql.NullString
			if err := rows.Scan(&rowid, &value); err != nil {
				_ = rows.Close()
				return err
			}
			if value.Valid && strings.TrimSpace(value.String) != "" &&
				!strings.HasPrefix(value.String, "enc:") {
				todo = append(todo, row{rowid: rowid, value: value.String})
			}
		}
		_ = rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
		for _, r := range todo {
			enc, err := ovcrypto.EncryptSecret(r.value, dataDir)
			if err != nil {
				return err
			}
			if _, err := x.Exec("UPDATE Setting SET bot_token = ? WHERE rowid = ?", enc, r.rowid); err != nil {
				return err
			}
		}
	}

	if tableNames(x)["Node"] && columnNames(x, "Node")["key"] {
		rows, err := x.Query("SELECT rowid, key FROM Node")
		if err != nil {
			return err
		}
		type row struct {
			rowid int64
			value string
		}
		var todo []row
		for rows.Next() {
			var rowid int64
			var value sql.NullString
			if err := rows.Scan(&rowid, &value); err != nil {
				_ = rows.Close()
				return err
			}
			if value.Valid && strings.TrimSpace(value.String) != "" &&
				!strings.HasPrefix(value.String, "enc:") {
				todo = append(todo, row{rowid: rowid, value: value.String})
			}
		}
		_ = rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
		for _, r := range todo {
			enc, err := ovcrypto.EncryptSecret(r.value, dataDir)
			if err != nil {
				return err
			}
			if _, err := x.Exec("UPDATE Node SET key = ? WHERE rowid = ?", enc, r.rowid); err != nil {
				return err
			}
		}
	}
	return nil
}

// deleteNonOwnerSessions removes sessions whose role is not owner.
func deleteNonOwnerSessions(x execer) error {
	if !tableNames(x)["Session"] {
		return nil
	}
	_, err := x.Exec("DELETE FROM Session WHERE role IS NULL OR role <> 'owner'")
	return err
}

// rebuildUsersWithAutoincrement creates pending_user_revocations and rebuilds
// the users table as INTEGER PRIMARY KEY AUTOINCREMENT, preserving all rows,
// columns, constraints and indexes. Seeds sqlite_sequence from MAX(id).
func rebuildUsersWithAutoincrement(x execer) error {
	if _, err := x.Exec(`CREATE TABLE IF NOT EXISTS PendingUserRevocation (
		node_id INTEGER NOT NULL,
		user_id INTEGER NOT NULL,
		user_uuid TEXT NOT NULL,
		user_name TEXT NOT NULL,
		created_at REAL NOT NULL,
		last_error TEXT NOT NULL DEFAULT '',
		PRIMARY KEY (node_id, user_id)
	)`); err != nil {
		return err
	}
	if !tableNames(x)["User"] {
		return nil
	}

	// Build a fresh users table with AUTOINCREMENT.
	if _, err := x.Exec("DROP TABLE IF EXISTS User_new"); err != nil {
		return err
	}
	ddl := strings.Replace(createTableSQL("User"), "CREATE TABLE IF NOT EXISTS User", "CREATE TABLE User_new", 1)
	if _, err := x.Exec(ddl); err != nil {
		return err
	}

	// Copy all existing rows/columns.
	cols := make([]string, 0, len(mappedColumns["User"]))
	for _, c := range mappedColumns["User"] {
		cols = append(cols, c.name)
	}
	colList := strings.Join(cols, ", ")
	copySQL := fmt.Sprintf("INSERT INTO User_new (%s) SELECT %s FROM User", colList, colList)
	if _, err := x.Exec(copySQL); err != nil {
		_, _ = x.Exec("DROP TABLE IF EXISTS User_new")
		return err
	}

	if _, err := x.Exec("DROP TABLE User"); err != nil {
		_, _ = x.Exec("DROP TABLE IF EXISTS User_new")
		return err
	}
	if _, err := x.Exec("ALTER TABLE User_new RENAME TO User"); err != nil {
		return err
	}

	// Seed the AUTOINCREMENT sequence so deleted highest IDs are not reused.
	// sqlite_sequence is created automatically by SQLite for AUTOINCREMENT tables.
	// Deleted-user undo snapshots may hold IDs above every live row; seeding
	// only from live MAX(id) would reissue that ID, and stale node CNs keyed
	// by numeric ID would then resolve to the new account.
	if _, err := x.Exec("DELETE FROM sqlite_sequence WHERE name = 'User'"); err != nil {
		return err
	}
	if _, err := x.Exec("INSERT INTO sqlite_sequence (name, seq) SELECT 'User', COALESCE(MAX(id), 0) FROM User"); err != nil {
		return err
	}
	if tableNames(x)["deleted_users"] {
		// Unrecoverable snapshots (malformed JSON) are skipped, not fatal:
		// json_extract raises on them, so only valid JSON seeds the sequence.
		if _, err := x.Exec(`UPDATE sqlite_sequence SET seq = MAX(seq, COALESCE((SELECT MAX(MAX(COALESCE(CAST(json_extract(snap_json, '$.ID') AS INTEGER), 0), COALESCE(CAST(json_extract(snap_json, '$.id') AS INTEGER), 0))) FROM deleted_users WHERE json_valid(snap_json)), 0)) WHERE name = 'User'`); err != nil {
			return err
		}
	}
	return nil
}
