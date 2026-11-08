// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

const (
	EncPrefix = "enc:v2:"
	keyFile   = "secret.key"
)

// GetOrCreateSecretKey loads or creates a 256-bit AES key outside the database.
// Stored in $DATA_DIR/secret.key with 0600 permissions.
//
// A missing or corrupt key is never replaced when the database already holds
// enc:v2: values: doing so would make every stored secret undecryptable.
// Callers must restore secret.key (or set OVM_SECRET_KEY) in that case.
func GetOrCreateSecretKey(dataDir string) ([]byte, error) {
	if envKey := strings.TrimSpace(os.Getenv("OVM_SECRET_KEY")); envKey != "" {
		if k, err := hex.DecodeString(envKey); err == nil && len(k) == 32 {
			return k, nil
		}
		return nil, fmt.Errorf("OVM_SECRET_KEY must be 64-char hex (32 bytes)")
	}

	if dataDir == "" {
		dataDir = "/var/lib/ovmanager"
	}
	_ = os.MkdirAll(dataDir, 0o700)
	target := filepath.Join(dataDir, keyFile)

	// Load an existing, well-formed key.
	if data, err := os.ReadFile(target); err == nil {
		trimmed := strings.TrimSpace(string(data))
		if k, err := hex.DecodeString(trimmed); err == nil && len(k) == 32 {
			return k, nil
		}
		if _, err := hex.DecodeString(trimmed); err == nil {
			return nil, fmt.Errorf("secret key at %s must be 64-char hex", target)
		}
		// File exists but is corrupt. Refuse to overwrite when encrypted
		// database values depend on it.
		if databaseHasEncryptedSecrets(dataDir) {
			return nil, fmt.Errorf("secret key at %s is corrupt and the database contains encrypted secrets; restore secret.key before continuing", target)
		}
	} else if !os.IsNotExist(err) {
		return nil, fmt.Errorf("reading secret key %s: %w", target, err)
	} else if databaseHasEncryptedSecrets(dataDir) {
		return nil, fmt.Errorf("secret key %s is missing but the database contains encrypted secrets; restore secret.key before continuing", target)
	}

	// Generate a new 32-byte key. Only reached when no encrypted database
	// values depend on a (possibly missing) key.
	newKey := make([]byte, 32)
	if _, err := io.ReadFull(rand.Reader, newKey); err != nil {
		return nil, fmt.Errorf("generating secret key: %w", err)
	}

	encoded := hex.EncodeToString(newKey)
	if err := os.WriteFile(target, []byte(encoded+"\n"), 0o600); err != nil {
		return nil, fmt.Errorf("writing secret key to %s: %w", target, err)
	}
	return newKey, nil
}

// databaseHasEncryptedSecrets reports whether the SQLite database in dataDir
// contains any enc:v2: secret values.
func databaseHasEncryptedSecrets(dataDir string) bool {
	dbPath := filepath.Join(dataDir, "ovmanager.db")
	if _, err := os.Stat(dbPath); err != nil {
		return false
	}
	conn, err := sql.Open("sqlite", "file:"+dbPath+"?mode=ro")
	if err != nil {
		return false
	}
	defer conn.Close()
	if err := conn.Ping(); err != nil {
		return false
	}
	for _, q := range []string{
		"SELECT 1 FROM settings WHERE bot_token LIKE 'enc:v2:%' LIMIT 1",
		"SELECT 1 FROM nodes WHERE key LIKE 'enc:v2:%' LIMIT 1",
	} {
		var one int
		if err := conn.QueryRow(q).Scan(&one); err == nil {
			return true
		}
	}
	return false
}

// EncryptSecret encrypts plaintext using AES-256-GCM and returns enc:v2:<base64>.
func EncryptSecret(plaintext string, dataDir string) (string, error) {
	if plaintext == "" || strings.HasPrefix(plaintext, EncPrefix) {
		return plaintext, nil
	}
	key, err := GetOrCreateSecretKey(dataDir)
	if err != nil {
		return "", err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return EncPrefix + base64.RawURLEncoding.EncodeToString(ciphertext), nil
}

// DecryptSecret decrypts an enc:v2: string using AES-256-GCM. Unencrypted plaintext returns as-is.
func DecryptSecret(stored string, dataDir string) (string, error) {
	if stored == "" || !strings.HasPrefix(stored, EncPrefix) {
		return stored, nil
	}
	key, err := GetOrCreateSecretKey(dataDir)
	if err != nil {
		return "", err
	}
	raw, err := base64.RawURLEncoding.DecodeString(strings.TrimPrefix(stored, EncPrefix))
	if err != nil {
		return "", fmt.Errorf("invalid base64 in encrypted secret: %w", err)
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonceSize := gcm.NonceSize()
	if len(raw) < nonceSize {
		return "", errors.New("ciphertext too short")
	}
	nonce, ct := raw[:nonceSize], raw[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ct, nil)
	if err != nil {
		return "", fmt.Errorf("decrypting secret: %w", err)
	}
	return string(plaintext), nil
}

// EncryptFile encrypts a file with AES-256-GCM and writes to dst with 0600 permissions.
func EncryptFile(srcPath, dstPath string, key []byte) error {
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return err
	}
	sealed := gcm.Seal(nonce, nonce, data, nil)
	return os.WriteFile(dstPath, sealed, 0o600)
}

// DecryptFile decrypts an AES-256-GCM file and writes to dst.
func DecryptFile(srcPath, dstPath string, key []byte) error {
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return err
	}
	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return errors.New("encrypted file too short")
	}
	nonce, ct := data[:nonceSize], data[nonceSize:]
	plain, err := gcm.Open(nil, nonce, ct, nil)
	if err != nil {
		return err
	}
	return os.WriteFile(dstPath, plain, 0o600)
}
