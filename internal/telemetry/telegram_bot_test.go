// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/db"
)

func newBotDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "bot.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	_, err = conn.Exec(`
CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_token VARCHAR, bot_enabled BOOLEAN, owner_telegram_id INTEGER);
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR, total BIGINT, used BIGINT, expiry_date VARCHAR, is_active BOOLEAN DEFAULT 1, max_logins INTEGER DEFAULT 1, telegram_chat_id INTEGER);
CREATE TABLE settings_kv (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at FLOAT);
CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor VARCHAR, action VARCHAR, target VARCHAR, detail VARCHAR);
	`)
	if err != nil {
		t.Fatalf("schema: %v", err)
	}
	_, _ = conn.Exec(`INSERT INTO settings (id, bot_token, bot_enabled, owner_telegram_id) VALUES (1, 'tok', 1, 999)`)
	_, _ = conn.Exec(`INSERT INTO users (id, uuid, name, total, used, expiry_date, is_active, max_logins) VALUES (1, 'u-aaa', 'alice', 1073741824, 0, '2030-01-01', 1, 3)`)
	return conn
}

type stubTelegram struct {
	srv     *httptest.Server
	sent    []map[string]any
	updates []tgUpdate
}

func startStub(t *testing.T, updates []tgUpdate) *stubTelegram {
	t.Helper()
	st := &stubTelegram{updates: updates}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if strings.HasSuffix(r.URL.Path, "/sendMessage") {
			st.sent = append(st.sent, body)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"ok":true}`))
			return
		}
		if strings.HasSuffix(r.URL.Path, "/getUpdates") {
			w.Header().Set("Content-Type", "application/json")
			ups := st.updates
			st.updates = nil
			_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": ups})
			return
		}
		w.WriteHeader(404)
	})
	st.srv = httptest.NewServer(mux)
	t.Cleanup(st.srv.Close)
	old := telegramAPIBase
	telegramAPIBase = st.srv.URL
	t.Cleanup(func() { telegramAPIBase = old })
	return st
}

func (s *stubTelegram) texts() []string {
	var out []string
	for _, m := range s.sent {
		if t, ok := m["text"].(string); ok {
			out = append(out, t)
		}
	}
	return out
}

func TestBotActivationBinds(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 42, "/start u-aaa")
	if len(st.sent) != 1 {
		t.Fatalf("sent %d, want 1", len(st.sent))
	}
	if !strings.Contains(st.texts()[0], "Linked") || !strings.Contains(st.texts()[0], "alice") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var chat int64
	_ = conn.QueryRow(`SELECT telegram_chat_id FROM users WHERE uuid='u-aaa'`).Scan(&chat)
	if chat != 42 {
		t.Fatalf("telegram_chat_id = %d, want 42", chat)
	}
}
func TestBotRebindNotifiesPreviousChat(t *testing.T) {
	conn := newBotDB(t)
	_, _ = conn.Exec(`UPDATE users SET telegram_chat_id=111 WHERE uuid='u-aaa'`)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 222, "/start u-aaa")
	found := false
	for _, m := range st.sent {
		if id, _ := m["chat_id"].(float64); int64(id) == 111 {
			found = true
			if txt, _ := m["text"].(string); !strings.Contains(txt, "re-linked") {
				t.Fatalf("rebind notice = %q", txt)
			}
		}
	}
	if !found {
		t.Fatalf("no rebind notice to previous chat 111; sent=%v", st.sent)
	}
	var chat int64
	_ = conn.QueryRow(`SELECT telegram_chat_id FROM users WHERE uuid='u-aaa'`).Scan(&chat)
	if chat != 222 {
		t.Fatalf("telegram_chat_id = %d, want 222", chat)
	}
}

func TestBotInvalidTokenRejected(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 42, "/start bogus")
	if !strings.Contains(st.texts()[0], "invalid") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var chat int
	_ = conn.QueryRow(`SELECT COUNT(*) FROM users WHERE telegram_chat_id=42`).Scan(&chat)
	if chat != 0 {
		t.Fatalf("chat bound for invalid token: %d", chat)
	}
}

func TestBotMeRequiresBinding(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 42, "/me")
	if !strings.Contains(st.texts()[0], "Not linked") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
}

func TestBotMeAfterBind(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	_, _ = conn.Exec(`UPDATE users SET telegram_chat_id=42 WHERE uuid='u-aaa'`)
	TgHandleText(conn, "tok", 999, 42, "/me")
	if !strings.Contains(st.texts()[0], "alice") {
		t.Fatalf("status = %q", st.texts()[0])
	}
}

func TestBotStrangerLockout(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 777, "/extend u-aaa 30")
	// strangers get the short menu, and no mutation happens
	var expiry string
	_ = conn.QueryRow(`SELECT expiry_date FROM users WHERE uuid='u-aaa'`).Scan(&expiry)
	if expiry != "2030-01-01" {
		t.Fatalf("expiry mutated by stranger: %s", expiry)
	}
	if len(st.sent) == 0 {
		t.Fatal("expected a reply for stranger")
	}
}

func TestBotOwnerExtend(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 999, "/extend u-aaa 30 2")
	if !strings.Contains(st.texts()[0], "Extended") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var total int64
	_ = conn.QueryRow(`SELECT total FROM users WHERE uuid='u-aaa'`).Scan(&total)
	if total != 1073741824+2*1024*1024*1024 {
		t.Fatalf("total = %d", total)
	}
}

func TestBotOwnerList(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 999, "/list")
	if !strings.Contains(st.texts()[0], "alice") {
		t.Fatalf("list = %q", st.texts()[0])
	}
}

func TestTgPollHandlesUpdate(t *testing.T) {
	conn := newBotDB(t)
	msg := &tgUpdate{UpdateID: 7}
	msg.Message = &struct {
		MessageID int `json:"message_id"`
		Chat      *struct {
			ID int64 `json:"id"`
		} `json:"chat"`
		Text string `json:"text"`
	}{MessageID: 1, Chat: &struct {
		ID int64 `json:"id"`
	}{ID: 42}, Text: "/start u-aaa"}
	st := startStub(t, []tgUpdate{*msg})
	if n := tgPollOnce(conn, "tok", 999); n != 1 {
		t.Fatalf("handled %d, want 1", n)
	}
	if len(st.sent) == 0 {
		t.Fatal("no reply sent")
	}
	if got := tgLastUpdate(conn); got != 7 {
		t.Fatalf("last update = %d, want 7", got)
	}
	_ = time.Now()
}
