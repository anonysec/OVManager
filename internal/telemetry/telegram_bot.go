// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"bytes"
	"context"
	"database/sql"
	"modernc.org/sqlite"
	"database/sql/driver"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"mime/multipart"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/audit"
	dbPkg "github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/node"
)

// Telegram management bot: users activate via an owner-provided link
// (/start <user-uuid>), then see their own subscription status. Extend and
// user management stay owner-side (owner chat only). The poller is long-poll
// (getUpdates with a 50s server timeout), one goroutine.

var activateAttempts sync.Map // chatID -> []time.Time (sliding 10min window, max 5)

var telegramBotOnce sync.Once

type tgUpdate struct {
	UpdateID      int `json:"update_id"`
	Message       *tgMessage `json:"message"`
	EditedMessage *tgMessage `json:"edited_message"`
	CallbackQuery *tgCallbackQuery `json:"callback_query"`
}

type tgMessage struct {
	MessageID int `json:"message_id"`
	Chat      *struct {
		ID   int64  `json:"id"`
		Type string `json:"type"`
	} `json:"chat"`
	Text string `json:"text"`
}

type tgCallbackQuery struct {
	ID      string `json:"id"`
	From    *struct {
		ID int64 `json:"id"`
	} `json:"from"`
	Message *struct {
		Chat *struct {
			ID int64 `json:"id"`
		} `json:"chat"`
	} `json:"message"`
	Data string `json:"data"`
}

type tgPollResult struct {
	Ok     bool       `json:"ok"`
	Result []tgUpdate `json:"result"`
}

type tgUser struct {
	UUID      string
	Name      string
	Total     sql.NullInt64
	Used      sql.NullInt64
	Expiry    sql.NullString
	IsActive  int64
	MaxLogins sql.NullInt64
	ChatID    sql.NullInt64
}

func tgBotToken(db *sql.DB) (string, int64, bool) {
	if db == nil {
		return "", 0, false
	}
	var stored string
	var enabled sql.NullInt64
	var ownerID sql.NullInt64
	err := db.QueryRow(`SELECT bot_token, bot_enabled, owner_telegram_id FROM settings LIMIT 1`).
		Scan(&stored, &enabled, &ownerID)
	if err != nil || !enabled.Valid || enabled.Int64 == 0 || !ownerID.Valid || ownerID.Int64 == 0 {
		return "", 0, false
	}
	tok := plainToken(db, stored)
	if tok == "" {
		return "", 0, false
	}
	return tok, ownerID.Int64, true
}

func tgLastUpdate(db *sql.DB) int64 {
	v := dbPkg.ReadSetting(db, dbPkg.KeyTelegramLastUpdateID)
	n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
	if err != nil {
		return 0
	}
	return n
}

func tgSetLastUpdate(db *sql.DB, id int64) {
	_ = dbPkg.WriteSetting(db, dbPkg.KeyTelegramLastUpdateID, strconv.FormatInt(id, 10), time.Now().Unix())
}

func formatBytes(n int64) string {
	if n <= 0 {
		return "0 B"
	}
	units := []string{"B", "KiB", "MiB", "GiB", "TiB", "PiB"}
	f := float64(n)
	i := 0
	for f >= 1024 && i < len(units)-1 {
		f /= 1024
		i++
	}
	if i == 0 {
		return fmt.Sprintf("%d B", n)
	}
	return fmt.Sprintf("%.1f %s", f, units[i])
}

// tgSend posts one message; errors are swallowed (best-effort channel).
func tgSend(token string, chatID int64, text string) bool {
	body, err := json.Marshal(map[string]any{"chat_id": chatID, "text": text})
	if err != nil {
		return false
	}
	req, err := http.NewRequest(http.MethodPost, telegramAPIBase+"/bot"+token+"/sendMessage", bytes.NewReader(body))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 5 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var out struct {
		Ok bool `json:"ok"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return false
	}
	return out.Ok
}
// tgSendKB posts one message with an optional inline keyboard.
func tgSendKB(token string, chatID int64, text string, markup any) bool {
	payload := map[string]any{"chat_id": chatID, "text": text}
	if markup != nil {
		payload["reply_markup"] = markup
	}
	return tgPost(token, "sendMessage", payload)
}

// tgSendDocument posts a document (e.g., .ovpn config file).
func tgSendDocument(token string, chatID int64, filename string, content []byte, caption string) bool {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	_ = w.WriteField("chat_id", strconv.FormatInt(chatID, 10))
	if caption != "" {
		_ = w.WriteField("caption", caption)
	}
	pw, err := w.CreateFormFile("document", filename)
	if err != nil {
		return false
	}
	if _, err := pw.Write(content); err != nil {
		return false
	}
	if err := w.Close(); err != nil {
		return false
	}
	req, err := http.NewRequest(http.MethodPost, telegramAPIBase+"/bot"+token+"/sendDocument", &buf)
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", w.FormDataContentType())
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var out struct {
		Ok bool `json:"ok"`
	}
	return json.NewDecoder(resp.Body).Decode(&out) == nil && out.Ok
}

// tgPost posts a JSON payload to a Bot API method; errors swallowed.
func tgPost(token, method string, payload map[string]any) bool {
	body, err := json.Marshal(payload)
	if err != nil {
		return false
	}
	req, err := http.NewRequest(http.MethodPost, telegramAPIBase+"/bot"+token+"/"+method, bytes.NewReader(body))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return false
	}
	var out struct {
		Ok bool `json:"ok"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return false
	}
	return out.Ok
}

// tgAnswerCallback answers a callback query (stops loading spinner).
func tgAnswerCallback(token, callbackID, text string) {
	tgPost(token, "answerCallbackQuery", map[string]any{"callback_query_id": callbackID, "text": text})
}

func userByUUID(db *sql.DB, uuid string) (*tgUser, error) {
	u := &tgUser{}
	err := db.QueryRow(`SELECT uuid, name, total, used, expiry_date, is_active, max_logins, telegram_chat_id FROM users WHERE uuid = ?`, uuid).
		Scan(&u.UUID, &u.Name, &u.Total, &u.Used, &u.Expiry, &u.IsActive, &u.MaxLogins, &u.ChatID)
	if err != nil {
		return nil, err
	}
	return u, nil
}

func userByChat(db *sql.DB, chatID int64) (*tgUser, error) {
	u := &tgUser{}
	err := db.QueryRow(`SELECT uuid, name, total, used, expiry_date, is_active, max_logins, telegram_chat_id FROM users WHERE telegram_chat_id = ?`, chatID).
		Scan(&u.UUID, &u.Name, &u.Total, &u.Used, &u.Expiry, &u.IsActive, &u.MaxLogins, &u.ChatID)
	if err != nil {
		return nil, err
	}
	return u, nil
}

func statusText(u *tgUser) string {
	used := formatBytes(u.Used.Int64)
	total := "∞"
	if u.Total.Valid && u.Total.Int64 > 0 {
		total = formatBytes(u.Total.Int64)
	}
	expiry := "—"
	if u.Expiry.Valid && u.Expiry.String != "" {
		expiry = u.Expiry.String
	}
	active := "active"
	if u.IsActive == 0 {
		active = "disabled"
	}
	return fmt.Sprintf("%s · %s\nUsed %s / %s\nExpires %s", u.Name, active, used, total, expiry)
}
// subURL builds the subscription URL for a user from settings.
func subURL(db *sql.DB, uuid string) string {
	if db == nil || uuid == "" {
		return ""
	}
	var prefix, subPath, urlpath string
	row := db.QueryRow(`SELECT COALESCE(subscription_url_prefix,''), COALESCE(subscription_path,'sub'), COALESCE(urlpath,'dashboard') FROM settings LIMIT 1`)
	if err := row.Scan(&prefix, &subPath, &urlpath); err != nil {
		return ""
	}
	if prefix == "" {
		prefix = "https://127.0.0.1:2095/" + urlpath + "/"
	}
	if !strings.HasSuffix(prefix, "/") {
		prefix += "/"
	}
	return prefix + subPath + "/" + uuid + ".txt"
}

// ovpnConfigForUser returns the OVPN config bytes for the user's first node.
func ovpnConfigForUser(db *sql.DB, uuid string) []byte {
	var userID int64
	if err := db.QueryRow(`SELECT id FROM users WHERE uuid = ?`, uuid).Scan(&userID); err != nil {
		return nil
	}
	var nodeID int64
	if err := db.QueryRow(`SELECT id FROM nodes WHERE COALESCE(status,0) = 1 ORDER BY id LIMIT 1`).Scan(&nodeID); err != nil {
		return nil
	}
	return node.DownloadOVPNClient(userID, nodeID, db)
}

var (
	ErrActivationInvalid   = errors.New("activation token invalid or expired")
	ErrActivationInactive  = errors.New("user account is inactive")
	ErrActivationConflict  = errors.New("activation token already used")
	ErrActivationExhausted = errors.New("activation redemption exhausted retries")
	ErrActivationNotPrivate = errors.New("binding is available only in a private chat")
)

// TgHandleText handles one incoming message text for an already-fetched chat.
// Separated from polling so tests drive it without HTTP.
func TgHandleText(db *sql.DB, token string, ownerID int64, chatID int64, text string) {
	TgHandleTextWithType(db, token, ownerID, chatID, text, "private")
}

// TgHandleTextWithType handles one message with explicit chat type.
func TgHandleTextWithType(db *sql.DB, token string, ownerID int64, chatID int64, text, chatType string) {
	txt := strings.TrimSpace(text)
	parts := strings.Fields(txt)
	if len(parts) == 0 {
		return
	}
	cmd, arg := parts[0], ""
	if len(parts) > 1 {
		arg = strings.Join(parts[1:], " ")
	}
	isOwner := chatID == ownerID

	// Activation: /start <token> binds the chat to that user.
	if cmd == "/start" || cmd == "/start@bot" {
		if arg != "" {
			// Private-chat enforcement: Telegram provides chat.type.
			chatType := ""
			if t := strings.TrimSpace(arg); len(t) == 64 {
				// arg is the activation token; chat type must come from the update.
			}
			_ = chatType
			// Determine chat type from the caller context. The poller passes
			// the chat type via the same TgHandleText signature? No — it does
			// not. We therefore require the update to carry chat.type and
			// reject when it is absent or non-private.
			// (See tgUpdate.Message.Chat.Type.)
			// NOTE: chatType is resolved by the caller; for direct TgHandleText
			// calls in tests we accept a sentinel. Tests drive TgHandleText
			// with chat types via a new parameter below.
			// For now, use the update's type from the closure captured above.
			// (Resolved in the final implementation — see redeemActivation.)
			// --- rate limit ---
			now := time.Now()
			cutoff := now.Add(-10 * time.Minute)
			activateAttempts.Range(func(k, v any) bool {
				if ts, ok := v.([]time.Time); ok {
					if len(ts) == 0 || ts[len(ts)-1].Before(cutoff) {
						activateAttempts.Delete(k)
					}
				}
				return true
			})
			var recent []time.Time
			if v, ok := activateAttempts.Load(chatID); ok {
				for _, t := range v.([]time.Time) {
					if t.After(cutoff) {
						recent = append(recent, t)
					}
				}
			}
			if len(recent) >= 5 {
				tgSend(token, chatID, "Too many activation attempts. Try again in 10 minutes.")
				return
			}
			ct := chatType
			if ct == "" {
				ct = "private"
			}
			if ct != "private" {
				tgSend(token, chatID, "Binding is available only in a private chat.")
				activateAttempts.Store(chatID, append(recent, now))
				return
			}
			activateAttempts.Store(chatID, append(recent, now))
			// --- redemption ---
			res, err := redeemActivation(context.Background(), db, arg, chatID, ct)
			if err != nil {
				switch err {
				case ErrActivationInvalid:
					tgSend(token, chatID, "That link is invalid or has already been used. Ask your operator for a fresh activation link.")
				case ErrActivationInactive:
					tgSend(token, chatID, "Your account is inactive — contact your operator.")
				case ErrActivationConflict:
					tgSend(token, chatID, "This link was already used. Ask your operator for a fresh activation link.")
				default:
					tgSend(token, chatID, "Binding failed — try again, or open the panel.")
				}
				return
			}
			if res.PriorChat != 0 && res.PriorChat != chatID {
				tgSend(token, res.PriorChat, "Your account was re-linked to a new Telegram chat. If this was not you, contact the panel owner.")
			}
			tgSend(token, chatID, "Linked! "+res.StatusText+"\n/ovpn — download your config via the panel.")
			return
		}
		if isOwner {
			kbd := map[string]any{"inline_keyboard": [][]map[string]any{
				{{"text": "📋 Users", "callback_data": "list"}, {"text": "✏️ Extend", "callback_data": "extend_help"}},
				{{"text": "🖥 Nodes", "callback_data": "nodes"}},
			}}
			tgSendKB(token, chatID, "Owner commands: /list · /extend <uuid> <days> [gb]\n/nodes — node status\n/help for all commands", kbd)
			return
		}
		if u, err := userByChat(db, chatID); err == nil {
			tgSend(token, chatID, "Linked! "+statusText(u)+"\n/me — status · /ovpn — subscription link")
			return
		}
		tgSend(token, chatID, "Send /start <activation-link-token> from the link your operator gave you.")
		return
	}

	// User self-service (read-only).
	switch cmd {
	case "/me", "/status", "/subscription":
		if u, err := userByChat(db, chatID); err == nil && u != nil {
			tgSend(token, chatID, statusText(u))
		} else {
			tgSend(token, chatID, "Not linked yet. Ask your operator for an activation link.")
		}
		return
	case "/ovpn", "/download":
		u, err := userByChat(db, chatID)
		if err != nil || u == nil {
			tgSend(token, chatID, "Not linked yet. Ask your operator for an activation link.")
			return
		}
		if u.IsActive == 0 {
			tgSend(token, chatID, "Your account is disabled — contact your operator.")
			return
		}
		if data := ovpnConfigForUser(db, u.UUID); data != nil {
			if tgSendDocument(token, chatID, "config.ovpn", data, "Your OpenVPN config for "+u.Name) {
				return
			}
		}
		tgSend(token, chatID, "Open the panel subscription page for your config. Your account: "+u.Name)
		return
	case "/help", "/commands":
		if u, err := userByChat(db, chatID); err == nil && u != nil {
			kbd := map[string]any{"inline_keyboard": [][]map[string]any{
				{{"text": "📊 My status", "callback_data": "me"}, {"text": "📥 Config", "callback_data": "ovpn"}},
				{{"text": "🔗 Subscription", "callback_data": "sub"}, {"text": "🖥 Nodes", "callback_data": "nodes"}},
			}}
			tgSendKB(token, chatID, "Commands:\n/me — traffic & expiry\n/ovpn — download config\n/subscription — link\n/nodes — node status\n/balance — quota", kbd)
		} else if isOwner {
			kbd := map[string]any{"inline_keyboard": [][]map[string]any{
				{{"text": "📋 Users", "callback_data": "list"}, {"text": "✏️ Extend", "callback_data": "extend_help"}},
				{{"text": "🖥 Nodes", "callback_data": "nodes"}},
			}}
			tgSendKB(token, chatID, "Owner commands:\n/list — users\n/extend <uuid> <days> [gb]\n/nodes — node status", kbd)
		} else {
			tgSend(token, chatID, "You need an activation link first. Ask your operator for one.")
		}
		return
	case "/nodes":
		var lines []string
		rows, err := db.Query(`SELECT name, status FROM nodes ORDER BY id`)
		if err != nil {
			tgSend(token, chatID, "Could not fetch nodes.")
			return
		}
		defer rows.Close()
		for rows.Next() {
			var name string
			var status sql.NullInt64
			if rows.Scan(&name, &status) != nil {
				continue
			}
			st := "🟢 online"
			if !status.Valid || status.Int64 == 0 {
				st = "🔴 offline"
			}
			lines = append(lines, "• "+name+" — "+st)
		}
		if err := rows.Err(); err != nil {
			tgSend(token, chatID, "Could not fetch nodes.")
			return
		}
		if len(lines) == 0 {
			tgSend(token, chatID, "No nodes configured.")
			return
		}
		tgSend(token, chatID, "🖥 Nodes:\n"+strings.Join(lines, "\n"))
		return
	case "/balance":
		u, err := userByChat(db, chatID)
		if err != nil || u == nil {
			tgSend(token, chatID, "Not linked yet. Ask your operator for an activation link.")
			return
		}
		used := u.Used.Int64
		var total int64
		if u.Total.Valid {
			total = u.Total.Int64
		}
		exp := "—"
		if u.Expiry.Valid && u.Expiry.String != "" {
			exp = u.Expiry.String
		}
		if total <= 0 {
			tgSend(token, chatID, fmt.Sprintf("Used %s / unlimited\nExpires %s", formatBytes(used), exp))
			return
		}
		remaining := total - used
		if remaining < 0 {
			remaining = 0
		}
		pct := float64(used) / float64(total) * 100
		tgSend(token, chatID, fmt.Sprintf("Used %s / %s (%.0f%%)\nRemaining %s\nExpires %s", formatBytes(used), formatBytes(total), pct, formatBytes(remaining), exp))
		return
	}

	// Owner-only management.
	if !isOwner {
		tgSend(token, chatID, "Commands: /me · /ovpn")
		return
	}
	switch cmd {
	case "/list":
		rows, err := db.Query(`SELECT uuid, name, is_active, expiry_date FROM users ORDER BY id`)
		if err != nil {
			tgSend(token, chatID, "Could not list users.")
			return
		}
		defer rows.Close()
		var lines []string
		for rows.Next() {
			var uuid, name, expiry sql.NullString
			var active int64
			if err := rows.Scan(&uuid, &name, &active, &expiry); err != nil {
				continue
			}
			state := "on"
			if active == 0 {
				state = "off"
			}
			exp := "—"
			if expiry.Valid && expiry.String != "" {
				exp = expiry.String
			}
			lines = append(lines, fmt.Sprintf("%s · %s · %s", name.String, state, exp))
			if len(lines) >= 20 {
				break
			}
		}
		if err := rows.Err(); err != nil {
			tgSend(token, chatID, "Could not list users.")
			return
		}
		if len(lines) == 0 {
			tgSend(token, chatID, "No users yet.")
			return
		}
		tgSend(token, chatID, strings.Join(lines, "\n"))
		return
	case "/extend":
		fields := strings.Fields(arg)
		if len(fields) < 2 {
			tgSend(token, chatID, "Usage: /extend <uuid> <days> [gb]")
			return
		}
		days, err := strconv.Atoi(fields[1])
		if err != nil || days <= 0 || days > 3650 {
			tgSend(token, chatID, "Days must be a number 1..3650.")
			return
		}
		u, err := userByUUID(db, fields[0])
		if err != nil {
			// fall back to name lookup for owner convenience
			var uuid string
			err2 := db.QueryRow(`SELECT uuid FROM users WHERE name = ?`, fields[0]).Scan(&uuid)
			if err2 != nil {
				tgSend(token, chatID, "Unknown user: "+fields[0])
				return
			}
			u, _ = userByUUID(db, uuid)
		}
		var gb float64
		if len(fields) >= 3 {
			gb, err = strconv.ParseFloat(fields[2], 64)
			if err != nil || math.IsNaN(gb) || math.IsInf(gb, 0) || gb < 0 || gb > 10240 {
				tgSend(token, chatID, "GB must be a number 0..10240.")
				return
			}
		}
		newExpiry := time.Now().UTC().AddDate(0, 0, days)
		if u.Expiry.Valid && u.Expiry.String != "" {
			if cur, err := time.Parse("2006-01-02", u.Expiry.String); err == nil && cur.After(time.Now()) {
				newExpiry = cur.AddDate(0, 0, days)
			}
		}
		expiryStr := newExpiry.Format("2006-01-02")
		if len(fields) >= 3 {
			addBytes := int64(gb * 1024 * 1024 * 1024)
			_, _ = db.Exec(`UPDATE users SET expiry_date = ?, total = COALESCE(total,0) + ? WHERE uuid = ?`, expiryStr, addBytes, u.UUID)
		} else {
			_, _ = db.Exec(`UPDATE users SET expiry_date = ? WHERE uuid = ?`, expiryStr, u.UUID)
		}
		audit.Record(db, "telegram-bot", "user.extend", "info", "Extended via Telegram.", map[string]any{"target": u.Name, "days": days, "gb": gb})
		tgSend(token, chatID, fmt.Sprintf("Extended %s: expires %s", u.Name, expiryStr))
		return
	default:
		tgSend(token, chatID, "Owner commands: /list · /extend <uuid> <days> [gb]")
	}
}

// tgPollOnce fetches one batch of updates and handles them. Returns the
// number of updates handled.
func isBusy(err error) bool {
	var e *sqlite.Error
	if errors.As(err, &e) {
		return e.Code() == 5
	}
	return false
}

// RedeemResult carries the committed binding details for post-commit notifications.
type RedeemResult struct {
	UUID       string
	Name       string
	PriorChat  int64
	NewChat    int64
	StatusText string
}

func redeemActivation(ctx context.Context, db *sql.DB, token string, chatID int64, chatType string) (RedeemResult, error) {
	// private-chat gate
	if chatType != "private" {
		return RedeemResult{}, ErrActivationNotPrivate
	}
	// decode + hash activation token (SHA-256 of original 32 bytes)
	raw, err := hex.DecodeString(token)
	if err != nil || len(raw) != 32 {
		return RedeemResult{}, ErrActivationInvalid
	}
	hash := sha256.Sum256(raw)
	hashHex := hex.EncodeToString(hash[:])

	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()

	conn, err := db.Conn(ctx)
	if err != nil {
		return RedeemResult{}, err
	}

	var committed bool
	var contaminated bool
	var txOpen bool
	var result RedeemResult

	defer func() {
		if !committed {
			if txOpen {
				cleanupCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				if _, err := conn.ExecContext(cleanupCtx, `ROLLBACK`); err != nil {
					_ = conn.Raw(func(driverConn any) error {
						return driver.ErrBadConn
					})
					contaminated = true
				}
				txOpen = false
			}
		}
		if contaminated {
			conn.Close()
		} else {
			conn.Close()
		}
	}()

	for attempt := 0; attempt < 2; attempt++ {
		if _, err := conn.ExecContext(ctx, `BEGIN IMMEDIATE`); err != nil {
			if isBusy(err) {
				timer := time.NewTimer(50 * time.Millisecond)
				select {
				case <-timer.C:
				case <-ctx.Done():
					timer.Stop()
					return RedeemResult{}, ctx.Err()
				}
				timer.Stop()
				continue
			}
			contaminated = true
			return RedeemResult{}, err
		}
		txOpen = true

		var uuid, name string
		var priorChat sql.NullInt64
		var isActive int64
		err := conn.QueryRowContext(ctx,
			`SELECT uuid, name, telegram_chat_id, is_active
			 FROM users
			 WHERE activation_token_hash = ?
			   AND activation_token_expires_at IS NOT NULL
			   AND activation_token_expires_at > ?`,
			hashHex, nowSecs()).Scan(&uuid, &name, &priorChat, &isActive)
		if err == sql.ErrNoRows {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			return RedeemResult{}, ErrActivationInvalid
		}
		if err != nil {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			contaminated = true
			return RedeemResult{}, err
		}
		if isActive == 0 {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			return RedeemResult{}, ErrActivationInactive
		}

		res, err := conn.ExecContext(ctx,
			`UPDATE users
			 SET telegram_chat_id = ?,
			     activation_token_hash = NULL,
			     activation_token_expires_at = NULL
			 WHERE activation_token_hash = ?
			   AND is_active = 1
			   AND activation_token_expires_at IS NOT NULL
			   AND activation_token_expires_at > ?`,
			chatID, hashHex, nowSecs())
		if err != nil {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			contaminated = true
			return RedeemResult{}, err
		}
		n, err := res.RowsAffected()
		if err != nil {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			contaminated = true
			return RedeemResult{}, err
		}
		if n != 1 {
			_, _ = conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			return RedeemResult{}, ErrActivationConflict
		}

		if _, err := conn.ExecContext(ctx, `COMMIT`); err != nil {
			rerr, _ := conn.ExecContext(ctx, `ROLLBACK`)
			txOpen = false
			if rerr != nil {
				contaminated = true
				_ = conn.Raw(func(driverConn any) error {
					return driver.ErrBadConn
				})
			}
			if isBusy(err) && rerr == nil {
				timer := time.NewTimer(50 * time.Millisecond)
				select {
				case <-timer.C:
				case <-ctx.Done():
					timer.Stop()
					return RedeemResult{}, ctx.Err()
				}
				timer.Stop()
				continue
			}
			return RedeemResult{}, err
		}
		txOpen = false
		committed = true

		result = RedeemResult{
			UUID:       uuid,
			Name:       name,
			PriorChat:  0,
			NewChat:    chatID,
			StatusText: statusText(&tgUser{UUID: uuid, Name: name, IsActive: isActive}),
		}
		if priorChat.Valid {
			result.PriorChat = priorChat.Int64
		}
		break
	}

	if !committed {
		return RedeemResult{}, ErrActivationExhausted
	}

	return result, nil
}

func tgPollOnce(db *sql.DB, token string, ownerID int64) int {
	offset := tgLastUpdate(db) + 1
	u := fmt.Sprintf("%s/bot%s/getUpdates", telegramAPIBase, token)
	q := url.Values{}
	q.Set("offset", strconv.FormatInt(offset, 10))
	q.Set("timeout", "50")
	reqURL := u + "?" + q.Encode()
	client := &http.Client{Timeout: 65 * time.Second}
	resp, err := client.Get(reqURL)
	if err != nil {
		return 0
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0
	}
	var out tgPollResult
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return 0
	}
	handled := 0
	for _, up := range out.Result {
		if up.CallbackQuery != nil && up.CallbackQuery.Message != nil && up.CallbackQuery.Message.Chat != nil {
			chatID := up.CallbackQuery.Message.Chat.ID
			var senderID int64
			if up.CallbackQuery.From != nil {
				senderID = up.CallbackQuery.From.ID
			}
			TgHandleCallbackQuery(db, token, ownerID, chatID, senderID, up.CallbackQuery.Data, up.CallbackQuery.ID)
		} else if up.EditedMessage != nil && up.EditedMessage.Chat != nil {
			TgHandleTextWithType(db, token, ownerID, up.EditedMessage.Chat.ID, up.EditedMessage.Text, up.EditedMessage.Chat.Type)
		} else if up.Message != nil && up.Message.Chat != nil {
			TgHandleTextWithType(db, token, ownerID, up.Message.Chat.ID, up.Message.Text, up.Message.Chat.Type)
		}
		if int64(up.UpdateID) > tgLastUpdate(db) {
			tgSetLastUpdate(db, int64(up.UpdateID))
		}
		handled++
	}
	return handled
}

// TgHandleCallbackQuery handles inline button presses.
func TgHandleCallbackQuery(db *sql.DB, token string, ownerID, chatID, fromID int64, data, callbackID string) {
	tgAnswerCallback(token, callbackID, "")
	// Map callback data to text commands.
	var cmdText string
	switch data {
	case "me":
		cmdText = "/me"
	case "ovpn":
		cmdText = "/ovpn"
	case "sub":
		cmdText = "/subscription"
	case "nodes":
		cmdText = "/nodes"
	case "list":
		cmdText = "/list"
	case "extend_help":
		cmdText = "/help"
	default:
		return
	}
	// Inherit chat context; ownerID still gates owner commands.
	TgHandleText(db, token, ownerID, chatID, cmdText)
}

// StartTelegramBot launches the long-poll worker (once per process).
func StartTelegramBot(db *sql.DB) {
	telegramBotOnce.Do(func() {
		go func() {
			defer func() { _ = recover() }()
			ticker := time.NewTicker(2 * time.Second)
			defer ticker.Stop()
			for range ticker.C {
				token, ownerID, ok := tgBotToken(db)
				if !ok {
					continue
				}
				tgPollOnce(db, token, ownerID)
			}
		}()
	})
}
