// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

// A failed encryption must abort the update, not clear the working token
// while answering success.
func TestBotConfigKeepsTokenWhenEncryptionFails(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`UPDATE Setting SET bot_token = 'enc:old'`); err != nil {
		t.Fatal(err)
	}

	prev := encryptBotToken
	encryptBotToken = func(string, string) (string, error) { return "", errors.New("key unavailable") }
	t.Cleanup(func() { encryptBotToken = prev })

	h := NewHandler(auth.NewService(conn, t.TempDir()))
	req := httptest.NewRequest(http.MethodPut, "/settings/bot", strings.NewReader(`{"bot_token":"new-token"}`))
	rec := httptest.NewRecorder()
	h.updateBotConfig(rec, req)

	var resp struct {
		Success bool `json:"success"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("response: %v (%s)", err, rec.Body.String())
	}
	if resp.Success {
		t.Fatal("update reported success after an encryption failure")
	}
	var token string
	if err := conn.QueryRow(`SELECT bot_token FROM Setting`).Scan(&token); err != nil {
		t.Fatal(err)
	}
	if token != "enc:old" {
		t.Fatalf("token = %q, want the existing value", token)
	}
}
