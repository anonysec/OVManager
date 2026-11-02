// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package crypto

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSecretKeyGenerationAndEncryption(t *testing.T) {
	tmp := t.TempDir()

	plain := "super-secret-node-api-key-12345"

	// 1. Encrypt secret
	enc, err := EncryptSecret(plain, tmp)
	if err != nil {
		t.Fatalf("EncryptSecret failed: %v", err)
	}

	if !strings.HasPrefix(enc, "enc:v2:") {
		t.Fatalf("expected enc:v2: prefix, got %q", enc)
	}

	if enc == plain {
		t.Fatalf("ciphertext equals plaintext!")
	}

	// 2. Check secret.key permissions on disk
	keyPath := filepath.Join(tmp, "secret.key")
	info, err := os.Stat(keyPath)
	if err != nil {
		t.Fatalf("stat secret.key: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("expected 0600 permissions, got %o", info.Mode().Perm())
	}

	// 3. Decrypt secret
	dec, err := DecryptSecret(enc, tmp)
	if err != nil {
		t.Fatalf("DecryptSecret failed: %v", err)
	}
	if dec != plain {
		t.Fatalf("decrypted = %q, want %q", dec, plain)
	}

	// 4. Backward compatibility: unencrypted plaintext returns as-is
	unencrypted := "plain-old-token"
	got, err := DecryptSecret(unencrypted, tmp)
	if err != nil {
		t.Fatalf("DecryptSecret on unencrypted failed: %v", err)
	}
	if got != unencrypted {
		t.Fatalf("expected unencrypted text preserved, got %q", got)
	}
}

func TestFileEncryptionAndDecryption(t *testing.T) {
	tmp := t.TempDir()
	src := filepath.Join(tmp, "test.db")
	enc := filepath.Join(tmp, "test.db.enc")
	dec := filepath.Join(tmp, "test_dec.db")

	data := []byte("SQLite format 3\x00sensitive database content")
	if err := os.WriteFile(src, data, 0o600); err != nil {
		t.Fatal(err)
	}

	key := []byte("01234567890123456789012345678901") // 32 bytes
	if err := EncryptFile(src, enc, key); err != nil {
		t.Fatalf("EncryptFile: %v", err)
	}

	if err := DecryptFile(enc, dec, key); err != nil {
		t.Fatalf("DecryptFile: %v", err)
	}

	decData, err := os.ReadFile(dec)
	if err != nil {
		t.Fatal(err)
	}
	if string(decData) != string(data) {
		t.Fatalf("decrypted file mismatch")
	}
}
