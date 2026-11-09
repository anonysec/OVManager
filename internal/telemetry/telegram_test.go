// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func newTelegramDB(t *testing.T, token string, enabled int64, chatID int64) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "tg.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_token VARCHAR, bot_enabled BOOLEAN, owner_telegram_id INTEGER)`); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO settings (id, bot_token, bot_enabled, owner_telegram_id) VALUES (1, ?, ?, ?)`, token, enabled, chatID); err != nil {
		t.Fatalf("seed: %v", err)
	}
	return conn
}

func TestSendTelegramDisabled(t *testing.T) {
	conn := newTelegramDB(t, "tok", 0, 123)
	if sendTelegram(conn, "hi") {
		t.Fatal("disabled bot sent a message")
	}
}

func TestSendTelegramNoToken(t *testing.T) {
	conn := newTelegramDB(t, "", 1, 123)
	if sendTelegram(conn, "hi") {
		t.Fatal("missing token sent a message")
	}
}

func TestSendTelegramNoChat(t *testing.T) {
	conn := newTelegramDB(t, "tok", 1, 0)
	if sendTelegram(conn, "hi") {
		t.Fatal("missing chat id sent a message")
	}
}

func TestSendTelegramNilDB(t *testing.T) {
	if sendTelegram(nil, "hi") {
		t.Fatal("nil db sent a message")
	}
}

func TestSendTelegramSends(t *testing.T) {
	var gotPath string
	var gotBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer srv.Close()
	old := telegramAPIBase
	telegramAPIBase = srv.URL
	defer func() { telegramAPIBase = old }()

	conn := newTelegramDB(t, "tok123", 1, 42)
	if !sendTelegram(conn, "hello ops") {
		t.Fatal("sendTelegram returned false on ok response")
	}
	if gotPath != "/bottok123/sendMessage" {
		t.Fatalf("path = %q, want /bottok123/sendMessage", gotPath)
	}
	if gotBody["chat_id"] != float64(42) || gotBody["text"] != "hello ops" {
		t.Fatalf("body = %v", gotBody)
	}
}

func TestSendTelegramAPIFailure(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":false}`))
	}))
	defer srv.Close()
	old := telegramAPIBase
	telegramAPIBase = srv.URL
	defer func() { telegramAPIBase = old }()

	conn := newTelegramDB(t, "tok123", 1, 42)
	if sendTelegram(conn, "hello") {
		t.Fatal("sendTelegram returned true on ok:false")
	}
}
