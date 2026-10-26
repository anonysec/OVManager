// Telegram parity tests (plan Task 4): the plain-text sender primitives, the
// masked settings reader, the worker's immediate-event scan (user expired /
// over-quota) with per-day dedupe, the daily summary text, and the settings
// endpoint masking of the bot token.
package tests

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/notify"
)

// telegramSchema is the slice of the schema the notify package touches.
const telegramSchema = `
CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_enabled BOOLEAN DEFAULT 0, bot_token VARCHAR,
  owner_telegram_id INTEGER, notify_expiry BOOLEAN DEFAULT 1, notify_traffic BOOLEAN DEFAULT 1,
  notify_node_down BOOLEAN DEFAULT 1, telegram_backup_enabled BOOLEAN DEFAULT 0,
  telegram_summary_time VARCHAR DEFAULT '09:00');
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR, total BIGINT, used BIGINT,
  expiry_date DATE, is_active BOOLEAN DEFAULT 1, max_logins INTEGER DEFAULT 1, last_online DATETIME);
`

// tgStub records bot-API calls (a sendMessage / sendDocument double).
type tgStub struct {
	mu    sync.Mutex
	calls []tgCall
	srv   *httptest.Server
}

type tgCall struct {
	method, path, chatID, text, contentType string
	hasParseMode                            bool
}

// newTGStub points notify.APIBase at a local double and restores it on cleanup.
func newTGStub(t *testing.T) *tgStub {
	t.Helper()
	stub := &tgStub{}
	stub.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = r.ParseForm()
		call := tgCall{
			method: r.Method, path: r.URL.Path,
			chatID:      r.FormValue("chat_id"),
			text:        r.FormValue("text"),
			contentType: r.Header.Get("Content-Type"),
		}
		_, call.hasParseMode = r.Form["parse_mode"]
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
		stub.mu.Lock()
		stub.calls = append(stub.calls, call)
		stub.mu.Unlock()
	}))
	t.Cleanup(stub.srv.Close)

	original := notify.APIBase
	notify.APIBase = stub.srv.URL
	t.Cleanup(func() { notify.APIBase = original })
	return stub
}

func (s *tgStub) n() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.calls)
}

func (s *tgStub) at(i int) tgCall {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls[i]
}

// TestTelegramSendMessage: plain text (no parse_mode), urlencoded form,
// chat_id and text verbatim on /bot<token>/sendMessage.
func TestTelegramSendMessage(t *testing.T) {
	stub := newTGStub(t)

	if err := notify.SendMessage("abc", "42", "hello  world"); err != nil {
		t.Fatalf("SendMessage: %v", err)
	}
	if stub.n() != 1 {
		t.Fatalf("unexpected call count %d", stub.n())
	}
	call := stub.at(0)
	if call.path != "/botabc/sendMessage" {
		t.Errorf("path = %q, want /botabc/sendMessage", call.path)
	}
	if !strings.HasPrefix(call.contentType, "application/x-www-form-urlencoded") {
		t.Errorf("content type = %q, want urlencoded form", call.contentType)
	}
	if call.hasParseMode {
		t.Error("parse_mode sent although plain text was requested")
	}
	if call.chatID != "42" {
		t.Errorf("chat_id = %q, want 42", call.chatID)
	}
	if call.text != "hello  world" {
		t.Errorf("text = %q, want verbatim %q (no escaping/trimming)", call.text, "hello  world")
	}
}

// TestTelegramSendMessageErrors: empty config and non-2xx never panic but must
// report. Notifications fail open — errors surface, callers log and move on.
func TestTelegramSendMessageErrors(t *testing.T) {
	if err := notify.SendMessage("", "42", "hi"); err == nil {
		t.Error("no token: expected an error")
	}
	if err := notify.SendMessage("tok", "", "hi"); err == nil {
		t.Error("no chat: expected an error")
	}

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"ok":false,"description":"Bad Request: chat not found"}`, http.StatusBadRequest)
	}))
	defer srv.Close()
	original := notify.APIBase
	notify.APIBase = srv.URL
	t.Cleanup(func() { notify.APIBase = original })

	err := notify.SendMessage("tok", "42", "hi")
	if err == nil {
		t.Fatal("status 400: expected an error")
	}
	if !strings.Contains(err.Error(), "400") {
		t.Errorf("error %q should mention the status", err)
	}
}

// TestTelegramMaskToken secrets: only the last four characters ever echo back.
func TestTelegramMaskToken(t *testing.T) {
	if got := notify.MaskToken("1234abcd5678efgh"); got != "…efgh" {
		t.Errorf("MaskToken = %q, want …efgh", got)
	}
	if got := notify.MaskToken(""); got != "" {
		t.Errorf("MaskToken(\"\") = %q, want empty", got)
	}
	if got := notify.MaskToken("ab"); got != "…" {
		t.Errorf("MaskToken(\"ab\") = %q, want a bare mask (2-4 char secrets never echo)", got)
	}
}

// TestTelegramSendDocument limits attachments: an oversized payload is refused
// locally, a small one posts as multipart with the file preserved.
func TestTelegramSendDocument(t *testing.T) {
	stub := newTGStub(t)
	if err := notify.SendDocument("abc", "42", "ovmanager-2026-10-18.db", []byte("db-bytes")); err != nil {
		t.Fatalf("SendDocument: %v", err)
	}
	call := stub.at(0)
	if call.method != http.MethodPost || call.path != "/botabc/sendDocument" {
		t.Errorf("path = %q, want /botabc/sendDocument", call.path)
	}

	big := make([]byte, notify.MaxDocumentBytes+1)
	if err := notify.SendDocument("abc", "42", "big.db", big); err == nil {
		t.Error("oversized document: expected a local refusal")
	}
	if stub.n() != 1 {
		t.Errorf("oversized document must not leave the process, calls = %d", stub.n())
	}
}

// TestTelegramLoadSettings: defaults on an empty row, values on a seeded one,
// and sane fallback when the stored time is garbage.
func TestTelegramLoadSettings(t *testing.T) {
	db := newNotifyDB(t)

	if p := notify.LoadSettings(db); p.Enabled || p.Configured {
		t.Errorf("empty settings: %+v", p)
	}
	if p := notify.LoadSettings(db); p.SummaryTime != "09:00" {
		t.Errorf("default summary time = %q, want 09:00", p.SummaryTime)
	}

	if _, err := db.Exec(`INSERT INTO settings (id, bot_enabled, bot_token, owner_telegram_id,
		telegram_summary_time) VALUES (1, 1, 'tok', 777, '07:15')`); err != nil {
		t.Fatalf("seed settings: %v", err)
	}
	p := notify.LoadSettings(db)
	if !p.Enabled || !p.Configured {
		t.Errorf("seeded settings: %+v", p)
	}
	if p.Token != "tok" || p.ChatID != "777" {
		t.Errorf("token/chat = %q/%q", p.Token, p.ChatID)
	}
	if p.SummaryTime != "07:15" {
		t.Errorf("summary time = %q, want 07:15", p.SummaryTime)
	}

	if _, err := db.Exec(`UPDATE settings SET telegram_summary_time = 'noon'`); err != nil {
		t.Fatalf("seed bad time: %v", err)
	}
	if p := notify.LoadSettings(db); p.SummaryTime != "09:00" {
		t.Errorf("garbage time must fall back to the default, got %q", p.SummaryTime)
	}
}

// TestTelegramWorkerEvents: immediate events fire once per day and the summary
// lands once per day; message transport is the stub, dedupe is per-day.
func TestTelegramWorkerEvents(t *testing.T) {
	db := newNotifyDB(t)
	if _, err := db.Exec(`INSERT INTO settings (id, bot_enabled, bot_token, owner_telegram_id)
		VALUES (1, 1, 'tok', '42')`); err != nil {
		t.Fatalf("seed settings: %v", err)
	}
	seed := `
	INSERT INTO users (name, expiry_date, is_active) VALUES ('alice', '2000-01-01', 1);
	INSERT INTO users (name, total, used) VALUES ('bob', 100, 101);
	INSERT INTO users (name, expiry_date) VALUES ('carol', '2999-01-01');
	`
	if _, err := db.Exec(seed); err != nil {
		t.Fatalf("seed users: %v", err)
	}

	stub := newTGStub(t)
	w := notify.NewWorker(db, nil, nil)

	day1 := time.Date(2026, 10, 1, 10, 30, 0, 0, time.UTC)
	w.Tick(day1)
	// Two immediate events + one daily summary.
	if got := stub.n(); got != 3 {
		t.Fatalf("day 1 sends = %d, want 3 (2 events + summary)", got)
	}
	texts := []string{}
	for i := 0; i < stub.n(); i++ {
		texts = append(texts, stub.at(i).text)
	}
	joined := strings.Join(texts, "\n")
	for _, want := range []string{"alice", "bob", "daily report"} {
		if !strings.Contains(joined, want) {
			t.Errorf("messages lack %q:\n%s", want, joined)
		}
	}

	// Same day again: both events and the summary stay silent.
	w.Tick(day1.Add(6 * time.Minute))
	if got := stub.n(); got != 3 {
		t.Fatalf("same-day re-tick sends = %d, want no new messages", got-3)
	}

	// Next day: the same events repeat (one per user per day), summary too.
	w.Tick(day1.Add(25 * time.Hour))
	if got := stub.n(); got != 6 {
		t.Fatalf("day 2 sends = %d, want 3 more", got)
	}
}

// TestTelegramWorkerDisabled: without an enabled bot the worker acts purely
// idle — no transport calls, no scans spilling over.
func TestTelegramWorkerDisabled(t *testing.T) {
	db := newNotifyDB(t)
	seed := `
	INSERT INTO settings (id, bot_token, owner_telegram_id) VALUES (1, 'tok', 42);
	INSERT INTO users (name, expiry_date) VALUES ('alice', '2000-01-01');
	`
	if _, err := db.Exec(seed); err != nil {
		t.Fatalf("seed: %v", err)
	}
	stub := newTGStub(t)
	w := notify.NewWorker(db, nil, nil)
	w.Tick(time.Date(2026, 10, 1, 10, 30, 0, 0, time.UTC))
	if stub.n() != 0 {
		t.Fatalf("disabled bot sent %d messages", stub.n())
	}
}

// TestTelegramTokenMaskedInSettings: the settings GET never echoes the stored
// token, and the summary time round-trips through the bot PUT.
func TestTelegramTokenMaskedInSettings(t *testing.T) {
	env := newPanelEnv(t)

	_, body := doJSON(t, "PUT", env.srv.URL+"/api/settings/bot", env.token,
		map[string]any{"bot_token": "1234abcd5678efgh", "telegram_summary_time": "07:15"})
	if body["success"] != true {
		t.Fatalf("PUT bot: %v", body)
	}

	_, body = doJSON(t, "GET", env.srv.URL+"/api/settings", env.token, nil)
	data, _ := body["data"].(map[string]any)
	if data == nil {
		t.Fatalf("no data in GET settings: %v", body)
	}
	if got, _ := data["bot_token"].(string); got != "…efgh" {
		t.Errorf("GET bot_token = %v, want last 4 chars only", data["bot_token"])
	}
	if data["telegram_summary_time"] != "07:15" {
		t.Errorf("GET telegram_summary_time = %v, want 07:15", data["telegram_summary_time"])
	}

	_, body = doJSON(t, "PUT", env.srv.URL+"/api/settings/bot", env.token,
		map[string]any{"telegram_summary_time": "not-a-time"})
	if body["success"] != false {
		t.Errorf("invalid summary time accepted: %v", body)
	}
}

// newNotifyDB is the throwaway DB the notify helpers run against; the shared
// tests schema's settings/users tables are dropped in favour of the narrower
// telegramSchema twin.
func newNotifyDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(`DROP TABLE IF EXISTS settings; DROP TABLE IF EXISTS users;` + telegramSchema); err != nil {
		t.Fatalf("telegram schema: %v", err)
	}
	return conn
}

// TestTelegramTransportFailureLogScrubbed: an unreachable host fails the send;
// the logged text must not contain the bot token.
func TestTelegramTransportFailureLogScrubbed(t *testing.T) {
	db := newNotifyDB(t)
	if _, err := db.Exec(`INSERT INTO settings (id, bot_enabled, bot_token, owner_telegram_id,
		notify_expiry, notify_traffic, telegram_backup_enabled, telegram_summary_time)
		VALUES (1, 1, 'SECRET_TOKEN', 7, 1, 1, 0, '09:00')`); err != nil {
		t.Fatalf("seed: %v", err)
	}

	original := notify.APIBase
	notify.APIBase = "http://127.0.0.1:1"
	t.Cleanup(func() { notify.APIBase = original })

	var buf bytes.Buffer
	log.SetOutput(&buf)
	t.Cleanup(func() { log.SetOutput(os.Stderr) })

	w := notify.NewWorker(db, nil, nil)
	w.Tick(time.Now())

	if strings.Contains(buf.String(), "SECRET_TOKEN") {
		t.Fatalf("token leaked into log: %s", buf.String())
	}
}
