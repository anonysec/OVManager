// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/internal/db"
)

func newBotDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "bot.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	_, err = conn.Exec(`
CREATE TABLE Setting (id INTEGER PRIMARY KEY, bot_token VARCHAR, bot_enabled BOOLEAN, owner_telegram_id INTEGER, telegram_last_update_id BIGINT DEFAULT 0);
CREATE TABLE User (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR, total BIGINT, used BIGINT, expiry_date VARCHAR, is_active BOOLEAN DEFAULT 1, max_logins INTEGER DEFAULT 1, telegram_chat_id INTEGER, activation_token_hash VARCHAR(64), activation_token_expires_at REAL);
CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor VARCHAR, action VARCHAR, target VARCHAR, detail VARCHAR);
	`)
	if err != nil {
		t.Fatalf("schema: %v", err)
	}
	_, _ = conn.Exec(`INSERT INTO Setting (id, bot_token, bot_enabled, owner_telegram_id) VALUES (1, 'tok', 1, 999)`)
	_, _ = conn.Exec(`INSERT INTO User (id, uuid, name, total, used, expiry_date, is_active, max_logins) VALUES (1, 'u-aaa', 'alice', 1073741824, 0, '2030-01-01', 1, 3)`)
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
	_, _ = conn.Exec(`UPDATE User SET activation_token_hash = ?, activation_token_expires_at = ? WHERE uuid = 'u-aaa'`,
		"e0e77a507412b120f6ede61f62295b1a7b2ff19d3dcc8f7253e51663470c888e", float64(time.Now().UnixNano())/1e9+3600)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 42, "/start aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	if len(st.sent) != 1 {
		t.Fatalf("sent %d, want 1", len(st.sent))
	}
	if !strings.Contains(st.texts()[0], "Linked") || !strings.Contains(st.texts()[0], "alice") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var chat int64
	_ = conn.QueryRow(`SELECT telegram_chat_id FROM User WHERE uuid='u-aaa'`).Scan(&chat)
	if chat != 42 {
		t.Fatalf("telegram_chat_id = %d, want 42", chat)
	}
}
func TestBotRebindNotifiesPreviousChat(t *testing.T) {
	conn := newBotDB(t)
	_, _ = conn.Exec(`UPDATE User SET telegram_chat_id=111 WHERE uuid='u-aaa'`)
	_, _ = conn.Exec(`UPDATE User SET activation_token_hash = ?, activation_token_expires_at = ? WHERE uuid = 'u-aaa'`,
		"4ca14526b2751b640d549ce7caf8ac39438592211a0ec370064d57666a682ad6", float64(time.Now().UnixNano())/1e9+3600)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 222, "/start bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
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
	_ = conn.QueryRow(`SELECT telegram_chat_id FROM User WHERE uuid='u-aaa'`).Scan(&chat)
	if chat != 222 {
		t.Fatalf("telegram_chat_id = %d, want 222", chat)
	}
}

func TestBotInvalidTokenRejected(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	TgHandleText(conn, "tok", 999, 42, "/start bogus")
	if !strings.Contains(st.texts()[0], "invalid") && !strings.Contains(st.texts()[0], "activation link") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var chat int
	_ = conn.QueryRow(`SELECT COUNT(*) FROM User WHERE telegram_chat_id=42`).Scan(&chat)
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
	_, _ = conn.Exec(`UPDATE User SET telegram_chat_id=42 WHERE uuid='u-aaa'`)
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
	_ = conn.QueryRow(`SELECT expiry_date FROM User WHERE uuid='u-aaa'`).Scan(&expiry)
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
	_ = conn.QueryRow(`SELECT total FROM User WHERE uuid='u-aaa'`).Scan(&total)
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
	msg.Message = &tgMessage{MessageID: 1, Text: "/start u-aaa"}
	msg.Message.Chat = &struct {
		ID   int64  `json:"id"`
		Type string `json:"type"`
	}{ID: 42, Type: "private"}
	st := startStub(t, []tgUpdate{*msg})
	if n := tgPollOnceCtx(context.Background(), conn, "tok", 999); n != 1 {
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
func TestBotActivationRateLimit(t *testing.T) {
	conn := newBotDB(t)
	_, _ = conn.Exec(`UPDATE User SET activation_token_hash = ?, activation_token_expires_at = ? WHERE uuid = 'u-aaa'`,
		"c2f480d4dda9f4522b9f6d590011636d904accfe59f12f9d66a0221c2558e3a2", float64(time.Now().UnixNano())/1e9+3600)
	activateAttempts.Delete(42)
	activateAttempts.Delete(99)
	st := startStub(t, nil)
	for range 5 {
		TgHandleText(conn, "tok", 999, 42, "/start cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")
	}
	if !strings.Contains(st.texts()[0], "Linked") {
		t.Fatalf("first attempt should bind, got %q", st.texts()[0])
	}
	st.sent = nil
	TgHandleText(conn, "tok", 999, 42, "/start cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc")
	if len(st.sent) != 1 || !strings.Contains(st.sent[0]["text"].(string), "Too many") {
		t.Fatalf("6th attempt should be rate-limited, sent=%v", st.sent)
	}
	// A different chat is not affected.
	st.sent = nil
	// A different chat is not rate-limited (it gets invalid-link, not Too many).
	st.sent = nil
	TgHandleText(conn, "tok", 999, 99, "/start bogus")
	if len(st.sent) == 0 {
		t.Fatal("no reply sent for other chat")
	}
	if strings.Contains(st.sent[0]["text"].(string), "Too many") {
		t.Fatalf("other chat should not be rate-limited, got %q", st.sent[0]["text"])
	}
}

// An unlimited user stays unlimited when traffic is added from the bot.
func TestBotOwnerExtendKeepsUnlimited(t *testing.T) {
	conn := newBotDB(t)
	st := startStub(t, nil)
	if _, err := conn.Exec(`UPDATE User SET total = NULL WHERE uuid = 'u-aaa'`); err != nil {
		t.Fatal(err)
	}
	TgHandleText(conn, "tok", 999, 999, "/extend u-aaa 30 2")
	if !strings.Contains(st.texts()[0], "Extended") {
		t.Fatalf("reply = %q", st.texts()[0])
	}
	var total sql.NullInt64
	if err := conn.QueryRow(`SELECT total FROM User WHERE uuid='u-aaa'`).Scan(&total); err != nil {
		t.Fatal(err)
	}
	if total.Valid {
		t.Fatalf("total = %d, want NULL (unlimited)", total.Int64)
	}
}
