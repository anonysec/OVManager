// Package notify is the Telegram ops channel (plan Task 4): a plain-text
// sender on stdlib HTTP, the masked settings reader, and the single worker
// goroutine that turns panel state into messages — the daily usage summary at
// a configurable wall-clock time (settings.telegram_summary_time, default
// 09:00), and immediate user expired / over-quota events, one per user per
// day. Node down/recovered, CPU and days-left thresholds are NOT re-detected
// here: they already live in telemetry.CollectMetrics (node_alerts +
// check_threshold_alerts), which this worker runs on a slow cadence so their
// dedupe (event_key → delivered, node transition state) stays in one place.
//
// Notifications fail open: every send error is logged and the flow continues —
// a Telegram hiccup never delays panel work. The transport is deliberately
// simple (application/x-www-form-urlencoded, no HTML parse mode), different
// from the no-long-poll policy: this is a read-only notify channel, not a
// command bot.
package notify

import (
	"bytes"
	"database/sql"
	"fmt"
	"log"
	"mime/multipart"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// APIBase is the Telegram Bot API root; tests point it at a local stub.
var APIBase = "https://api.telegram.org"

const sendTimeout = 15 * time.Second

// sendHTTPClient is single so keep-alives are reused.
var sendHTTPClient = &http.Client{Timeout: sendTimeout}

// MaxDocumentBytes is the size cap for attached documents (backups).
const MaxDocumentBytes = 2 << 20

// SendMessage posts one message in Telegram's default (plain text) mode:
// form-encoded chat_id + text. Errors carry the transport failure or the
// non-2xx status and body snippet; nothing blocks the caller on success.
func SendMessage(token, chatID, text string) error {
	if strings.TrimSpace(token) == "" {
		return fmt.Errorf("telegram: bot token not configured")
	}
	if strings.TrimSpace(chatID) == "" {
		return fmt.Errorf("telegram: chat id not configured")
	}
	form := url.Values{"chat_id": {strings.TrimSpace(chatID)}, "text": {text}}
	resp, err := sendHTTPClient.PostForm(APIBase+"/bot"+strings.TrimSpace(token)+"/sendMessage", form)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return checkTelegramResponse(resp)
}

// SendDocument uploads name/data as a multipart document (the daily backup
// attachment). Payloads above MaxDocumentBytes are refused locally.
func SendDocument(token, chatID, name string, data []byte) error {
	if len(data) > MaxDocumentBytes {
		return fmt.Errorf("telegram: document %q is %d bytes, over the %d byte cap",
			name, len(data), MaxDocumentBytes)
	}
	if strings.TrimSpace(token) == "" || strings.TrimSpace(chatID) == "" {
		return fmt.Errorf("telegram: bot not configured")
	}
	body := &bytes.Buffer{}
	mw := multipart.NewWriter(body)
	if err := mw.WriteField("chat_id", strings.TrimSpace(chatID)); err != nil {
		return err
	}
	part, err := mw.CreateFormFile("document", name)
	if err != nil {
		return err
	}
	if _, err := part.Write(data); err != nil {
		return err
	}
	if err := mw.Close(); err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost,
		APIBase+"/bot"+strings.TrimSpace(token)+"/sendDocument", body)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())
	resp, err := sendHTTPClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return checkTelegramResponse(resp)
}

func checkTelegramResponse(resp *http.Response) error {
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	buf := make([]byte, 4096)
	n, _ := resp.Body.Read(buf)
	return fmt.Errorf("telegram: status %d: %s", resp.StatusCode, strings.TrimSpace(string(buf[:n])))
}

// MaskToken echoes only the last four characters of a stored bot token — the
// shape the settings GET serves back, so the secret never leaves the row.
func MaskToken(token string) string {
	token = strings.TrimSpace(token)
	if token == "" {
		return ""
	}
	if len(token) <= 4 {
		return "…" // short secrets never echo in whole
	}
	return "…" + token[len(token)-4:]
}

// --- settings (the settings row, read fresh per tick) ---

// Settings is the Telegram slice of the settings row.
type Settings struct {
	Token, ChatID, SummaryTime  string
	Enabled, Configured         bool
	NotifyExpiry, NotifyTraffic bool
	NotifyBackup                bool
}

// LoadSettings reads the Telegram columns. A missing row stays disabled; a
// schema without telegram_summary_time (fresh reconcile handles instant
// upgrades, handcrafted test schemas do not) keeps the default time.
func LoadSettings(db *sql.DB) Settings {
	s := Settings{SummaryTime: "09:00", NotifyExpiry: true, NotifyTraffic: true}
	if db == nil {
		return s
	}
	var enabled, ne, nt, nb sql.NullInt64
	var token, st sql.NullString
	var chat sql.NullInt64
	err := db.QueryRow(`SELECT bot_enabled, bot_token, owner_telegram_id,
		notify_expiry, notify_traffic, telegram_backup_enabled, telegram_summary_time
		FROM settings LIMIT 1`).
		Scan(&enabled, &token, &chat, &ne, &nt, &nb, &st)
	if err != nil {
		// Retry without the summary-time column (settings row may simply be
		// absent or legacy).
		if qerr := db.QueryRow(`SELECT bot_enabled, bot_token, owner_telegram_id,
			notify_expiry, notify_traffic, telegram_backup_enabled
			FROM settings LIMIT 1`).
			Scan(&enabled, &token, &chat, &ne, &nt, &nb); qerr != nil {
			return s
		}
	}
	s.Enabled = enabled.Int64 != 0
	s.Configured = token.Valid && token.String != ""
	s.Token = token.String
	if chat.Valid {
		s.ChatID = strconv.FormatInt(chat.Int64, 10)
	}
	s.NotifyExpiry = ne.Valid && ne.Int64 != 0
	s.NotifyTraffic = nt.Valid && nt.Int64 != 0
	s.NotifyBackup = nb.Valid && nb.Int64 != 0
	if st.Valid {
		if v := strings.TrimSpace(st.String); validHHMM(v) {
			s.SummaryTime = v
		}
	}
	return s
}

// ready is whether messages can go out at all: the row must enable the bot and
// carry both credentials.
func (s Settings) ready() bool {
	return s.Enabled && s.Configured && s.ChatID != ""
}

func validHHMM(v string) bool {
	_, err := time.Parse("15:04", v)
	return err == nil
}

// --- events ---

// Event is one immediate notification.
type Event struct {
	Key  string // dedupe key; the worker sends each key at most once per day
	Text string
	Kind string // "expired" | "quota" — selects the notify_* toggle
}

// ImmediateEvents scans users with the same semantics the activation gate
// uses (expired = strict date before today; over quota = total > 0 and
// total <= used, i.e. quota walked into).
func ImmediateEvents(db *sql.DB, now time.Time) []Event {
	if db == nil {
		return nil
	}
	rows, err := db.Query(`SELECT name, COALESCE(total,0), COALESCE(used,0), COALESCE(expiry_date,''), COALESCE(is_active,1) FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	today := now.Format("2006-01-02")
	var out []Event
	for rows.Next() {
		var name string
		var total, used, active int64
		var expiry string
		if rows.Scan(&name, &total, &used, &expiry, &active) != nil {
			continue
		}
		if name == "" {
			continue
		}
		if len(expiry) >= 10 && expiry[:10] < today {
			out = append(out, Event{
				Key: "expired:" + name, Kind: "expired",
				Text: "🚨 User " + name + " expired on " + expiry[:10] + ".",
			})
		}
		if total > 0 && used >= total {
			out = append(out, Event{
				Key: "quota:" + name, Kind: "quota",
				Text: fmt.Sprintf("🚫 User %s reached the traffic quota (%d/%d bytes).", name, used, total),
			})
		}
		_ = active // disabled users still surface the state change once
	}
	return out
}

// --- worker (one goroutine, minute cadence) ---

const (
	workerTick   = time.Minute      // wall-clock resolution of event/summary gating
	collectEvery = 30 * time.Minute // metric + threshold sweep cadence
)

// Worker turns settings + users state into Telegram messages. The DB handle
// is guarded: a restore swaps the pool underneath a running worker
// (SwapDB), and an unguarded field would race Tick against the swap.
type Worker struct {
	dbmu sync.RWMutex
	db   *sql.DB
	// DailyBackup, when set, produces (name, bytes) of a database snapshot for
	// the summary attachment; nil (or empty bytes) skips the attachment.
	DailyBackup func() (string, []byte)
	// Collect is the periodic metrics sweep (telemetry.CollectMetrics in
	// production); it drives the node down/up transitions, the CPU and
	// days-left/usage thresholds — each with its own dedupe — plus snapshot
	// history. Nil (tests) skips the sweep.
	Collect func(*sql.DB)

	sentDay     map[string]string // dedupe key → day last sent
	lastCollect time.Time
}

// NewWorker builds a worker over the data DB.
func NewWorker(db *sql.DB, dailyBackup func() (string, []byte), collect func(*sql.DB)) *Worker {
	return &Worker{
		db: db, DailyBackup: dailyBackup, Collect: collect,
		sentDay: map[string]string{},
	}
}

// DB returns the live database handle (swap-safe).
func (w *Worker) DB() *sql.DB {
	w.dbmu.RLock()
	defer w.dbmu.RUnlock()
	return w.db
}

// SwapDB atomically replaces the live database handle; called after a restore
// reopens the pool so the next Tick stops reading the replaced inode.
func (w *Worker) SwapDB(fresh *sql.DB) {
	w.dbmu.Lock()
	defer w.dbmu.Unlock()
	w.db = fresh
}

var (
	workerOnce sync.Once
	running    atomic.Pointer[Worker]
)

// StartWorker runs the worker loop once per process. A short starting delay
// mirrors the ACME renewal worker so boot traffic settles first.
func StartWorker(db *sql.DB, dailyBackup func() (string, []byte), collect func(*sql.DB)) {
	workerOnce.Do(func() {
		w := NewWorker(db, dailyBackup, collect)
		running.Store(w)
		go func() {
			defer func() { recover() }()
			time.Sleep(2 * time.Minute)
			ticker := time.NewTicker(workerTick)
			defer ticker.Stop()
			for now := range ticker.C {
				w.Tick(now)
			}
		}()
	})
}

// Running returns the worker StartWorker launched, or nil before that.
func Running() *Worker { return running.Load() }

// Tick is one worker step: collector sweep, immediate events, the daily
// summary. Everything is guarded by the settings row; without a ready bot it
// is a no-op.
func (w *Worker) Tick(now time.Time) {
	db := w.DB() // one handle per tick; a swap takes effect on the next one
	p := LoadSettings(db)
	if !p.ready() {
		return
	}
	if w.lastCollect.IsZero() || now.Sub(w.lastCollect) >= collectEvery {
		w.lastCollect = now
		if w.Collect != nil {
			w.Collect(db)
		}
	}

	day := now.Format("2006-01-02")
	for _, ev := range ImmediateEvents(db, now) {
		switch ev.Kind {
		case "expired":
			if !p.NotifyExpiry {
				continue
			}
		case "quota":
			if !p.NotifyTraffic {
				continue
			}
		}
		if !w.sendOnce(p, ev.Key, ev.Text, day) {
			continue
		}
	}

	if summaryTime, err := time.Parse("15:04", p.SummaryTime); err == nil {
		clock := now.Hour()*100 + now.Minute()
		due := summaryTime.Hour()*100 + summaryTime.Minute()
		if clock >= due {
			w.sendOnce(p, "daily", SummaryText(db, now), day)
		}
	}
}

// sendOnce sends keyed text once per day, marking sent only on a successful
// post — a failure retries on the next tick.
func (w *Worker) sendOnce(p Settings, key, text, day string) bool {
	if w.sentDay[key] == day {
		return false
	}
	err := SendMessage(p.Token, p.ChatID, text)
	if err == nil && p.NotifyBackup && key == "daily" && w.DailyBackup != nil {
		if name, data := w.DailyBackup(); len(data) > 0 {
			if derr := SendDocument(p.Token, p.ChatID, name, data); derr != nil {
				log.Printf("telegram: backup attach failed: %v", derr)
			}
		}
	}
	if err != nil {
		log.Printf("telegram: %s: %v", key, err)
		return false
	}
	w.sentDay[key] = day
	return true
}

// SummaryText is the daily usage report: users by state, the expiring-in-3-days
// batch (the alert_days_left window), and nothing else — concise on purpose.
func SummaryText(db *sql.DB, now time.Time) string {
	rows, err := db.Query(`SELECT name, COALESCE(total,0), COALESCE(used,0), COALESCE(expiry_date,''), COALESCE(is_active,1) FROM users`)
	if err != nil {
		return ""
	}
	defer rows.Close()
	today := now.Format("2006-01-02")
	var daysLeft = 3
	if v := alertDaysLeft(db); v > 0 {
		daysLeft = v
	}
	total, active, disabled, expired, quota := 0, 0, 0, 0, 0
	expiring := []string{}
	for rows.Next() {
		var name string
		var totalQuota, used int64
		var expiry string
		var active1 int64
		if rows.Scan(&name, &totalQuota, &used, &expiry, &active1) != nil {
			continue
		}
		total++
		if active1 != 0 {
			active++
		} else {
			disabled++
		}
		if len(expiry) >= 10 && expiry[:10] != "" {
			e, eerr := time.Parse("2006-01-02", expiry[:10])
			t, terr := time.Parse("2006-01-02", today)
			if eerr == nil && terr == nil {
				d := int(e.Sub(t).Hours() / 24)
				switch {
				case d < 0:
					expired++
				case d <= daysLeft:
					expiring = append(expiring, fmt.Sprintf("%s (%d days)", name, d))
				}
			}
		}
		if totalQuota > 0 && used >= totalQuota {
			quota++
		}
	}
	lines := []string{
		"📊 OVManager daily report — " + today,
		fmt.Sprintf("Users: %d total, %d active, %d disabled, %d expired, %d over quota",
			total, active, disabled, expired, quota),
	}
	if len(expiring) > 0 {
		lines = append(lines, fmt.Sprintf("Expiring within %d days: %s",
			daysLeft, strings.Join(expiring, ", ")))
	}
	return strings.Join(lines, "\n")
}

func alertDaysLeft(db *sql.DB) int {
	var v sql.NullInt64
	if db.QueryRow(`SELECT alert_days_left FROM settings LIMIT 1`).Scan(&v) != nil || !v.Valid {
		return 0
	}
	return int(v.Int64)
}
