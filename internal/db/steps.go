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

	"github.com/anonysec/OVManager/go/internal/config"
	ovcrypto "github.com/anonysec/OVManager/go/internal/crypto"
)

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
		"INSERT OR IGNORE INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes, meta_json) " +
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
// environment and decrypts any remaining “enc:“ rows. A row that fails to
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

// --- backend-aware version store (scaffolding for multi-backend support) ---
//
// SQLite keeps using PRAGMA user_version for backward compatibility with
// existing databases. Any other backend uses a _schema_version table. When a
// new driver is wired in internal/db/config.go, add its case to
// versionGet/versionSet and implement the table store below (already generic).

// versionGet reads the current schema version for backend.
func versionGet(conn *sql.DB, backend Backend) (int, error) {
	switch backend {
	case BackendSQLite, "":
		return userVersion(conn)
	default:
		return tableVersion(conn)
	}
}

// versionSet writes the schema version for backend.
func versionSet(x execer, backend Backend, v int) error {
	switch backend {
	case BackendSQLite, "":
		return stamp(x, v)
	default:
		return stampTable(x, v)
	}
}

// tableVersion reads _schema_version (creates it if missing).
func tableVersion(conn *sql.DB) (int, error) {
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER NOT NULL)`); err != nil {
		return 0, err
	}
	var v int
	row := conn.QueryRow(`SELECT COALESCE(MAX(version), 0) FROM _schema_version`)
	if err := row.Scan(&v); err != nil {
		return 0, err
	}
	return v, nil
}

// stampTable writes a new version row.
func stampTable(x execer, v int) error {
	if _, err := x.Exec(`INSERT INTO _schema_version (version) VALUES (?)`, v); err != nil {
		return err
	}
	return nil
}

// encryptStoredSecrets encrypts plaintext nodes.key and settings.bot_token values
// that are not already enc:v2:. Idempotent and transactional: any failure
// aborts the migration so no partial state is stamped.
func encryptStoredSecrets(x execer) error {
	dataDir := config.EnvOrFile("DATA_DIR", "data")

	if tableNames(x)["settings"] && columnNames(x, "settings")["bot_token"] {
		rows, err := x.Query("SELECT rowid, bot_token FROM settings")
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
			if _, err := x.Exec("UPDATE settings SET bot_token = ? WHERE rowid = ?", enc, r.rowid); err != nil {
				return err
			}
		}
	}

	if tableNames(x)["nodes"] && columnNames(x, "nodes")["key"] {
		rows, err := x.Query("SELECT rowid, key FROM nodes")
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
			if _, err := x.Exec("UPDATE nodes SET key = ? WHERE rowid = ?", enc, r.rowid); err != nil {
				return err
			}
		}
	}
	return nil
}

// deleteNonOwnerSessions removes sessions whose role is not owner.
func deleteNonOwnerSessions(x execer) error {
	if !tableNames(x)["sessions"] {
		return nil
	}
	_, err := x.Exec("DELETE FROM sessions WHERE role IS NULL OR role <> 'owner'")
	return err
}
