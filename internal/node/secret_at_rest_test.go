// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/crypto"
	_ "modernc.org/sqlite"
)

func TestNodeKeyAtRestEncryption(t *testing.T) {
	d := setupNodeTestDB(t)

	rawKey := "plain-node-api-key-98765"
	req := nodeCreate{
		Name:    "node-enc-test",
		Address: "10.0.0.1",
		Key:     &rawKey,
	}

	id, err := createNode(d, req, "")
	if err != nil {
		t.Fatalf("createNode failed: %v", err)
	}

	// 1. Inspect raw database column: must be encrypted with enc:v2: prefix
	var rawStoredKey string
	err = d.QueryRow("SELECT key FROM nodes WHERE id = ?", id).Scan(&rawStoredKey)
	if err != nil {
		t.Fatalf("QueryRow key: %v", err)
	}
	if !strings.HasPrefix(rawStoredKey, crypto.EncPrefix) {
		t.Fatalf("SECURITY FLAW: key is not encrypted in database! raw = %q", rawStoredKey)
	}
	if rawStoredKey == rawKey {
		t.Fatalf("SECURITY FLAW: stored key equals plaintext!")
	}

	// 2. Read through GetNodeByID: must be transparently decrypted
	loaded := GetNodeByID(d, id)
	if loaded == nil {
		t.Fatalf("GetNodeByID returned nil")
	}
	if loaded.Key != rawKey {
		t.Fatalf("loaded.Key = %q, want %q", loaded.Key, rawKey)
	}
}
