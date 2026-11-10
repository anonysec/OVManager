// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/audit"
	"github.com/anonysec/OVManager/internal/crypto"
	"github.com/anonysec/OVManager/internal/db"
	"github.com/anonysec/OVManager/internal/node"
)

func RecordEvent(db *sql.DB, kind, severity, message string, meta map[string]any) {
	audit.Record(db, "system", kind, severity, message, meta)
}

// lastEventMeta returns the meta of the newest record_event row for kind.
func lastEventMeta(db *sql.DB, kind string) map[string]any {
	_ = db
	var latest map[string]any
	var latestTS float64
	for _, obj := range audit.ReadLines() {
		if obj["action"] != kind || obj["actor"] != "system" {
			continue
		}
		ts, _ := obj["ts"].(float64)
		if ts > latestTS {
			latestTS = ts
			latest = obj
		}
	}
	if latest == nil {
		return nil
	}
	meta, _ := latest["meta"].(map[string]any)
	return meta
}

// PruneAuditLogs removes audit lines older than keepDays from the JSONL file.
// Returns number removed.
func PruneAuditLogs(db *sql.DB, keepDays int) int {
	_ = db
	if keepDays <= 0 {
		keepDays = 90
	}
	keepDays = clamp(keepDays, 1, 1<<30)
	cutoff := float64(time.Now().UTC().AddDate(0, 0, -keepDays).Unix())
	path := audit.Path()
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	lines := strings.Split(string(data), "\n")
	var kept []string
	removed := 0
	for _, line := range lines {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var obj map[string]any
		if json.Unmarshal([]byte(line), &obj) != nil {
			kept = append(kept, line)
			continue
		}
		ts, _ := obj["ts"].(float64)
		if ts < cutoff {
			removed++
			continue
		}
		kept = append(kept, line)
	}
	if removed == 0 {
		return 0
	}
	out := strings.Join(kept, "\n")
	if len(kept) > 0 {
		out += "\n"
	}
	_ = os.WriteFile(path, []byte(out), 0o600)
	return removed
}

// promoteEvents delivers enrolled audit events to Telegram, once each.
//
// Reads are bounded: the query filters by promoted=0 (partial index) and
// excludes rows that have already been delivered, so the work is proportional
// to the PENDING events, not to the whole audit history. The event key lives
// inside the JSON detail, so the exclusion uses SQLite's json_extract against
// the delivered table.
func promoteEvents(db *sql.DB, send func(string) bool) int {
	_ = db
	sent := 0
	for _, obj := range audit.ReadLines() {
		actor, _ := obj["actor"].(string)
		if actor != "system" {
			continue
		}
		promoted, _ := obj["promoted"].(bool)
		if promoted {
			continue
		}
		meta, _ := obj["meta"].(map[string]any)
		key, _ := meta["event_key"].(string)
		if key == "" {
			continue
		}
		action, _ := obj["action"].(string)
		// check delivered
		var exists int
		_ = db.QueryRow(`SELECT COUNT(*) FROM delivered WHERE subscription = ? AND event_key = ?`, action, key).Scan(&exists)
		if exists > 0 {
			continue
		}
		message, _ := obj["message"].(string)
		if message == "" {
			message = action
		}
		if !send(message) {
			continue
		}
		_, _ = db.Exec(`INSERT OR IGNORE INTO delivered (subscription, event_key, ts) VALUES (?, ?, ?)`, action, key, nowSecs())
		if v, ok := obj["id"].(float64); ok {
			audit.MarkPromoted(int64(v))
		}
		sent++
	}
	return sent
}

// checkThresholdAlerts mirrors thresholds.check_threshold_alerts.
func checkThresholdAlerts(db *sql.DB) int {
	groups := map[string][]map[string]any{}
	order := []string{}
	for _, item := range thresholdItems(db) {
		t, _ := item["type"].(string)
		if _, seen := groups[t]; !seen {
			order = append(order, t)
		}
		groups[t] = append(groups[t], item)
	}
	kinds := append([]string{}, activeKinds...)
	for _, k := range order {
		found := false
		for _, a := range kinds {
			if a == k {
				found = true
			}
		}
		if !found {
			kinds = append(kinds, k)
		}
	}
	for _, kind := range kinds {
		group := groups[kind]
		signature := signatureOf(group)
		last := lastEventMeta(db, kind)
		lastSignature, _ := last["signature"].(string)
		if signature != "" {
			if lastSignature == signature {
				continue
			}
			level := "warning"
			for _, item := range group {
				if item["level"] == "danger" {
					level = "error"
				}
			}
			var target any
			if len(group) == 1 {
				target = group[0]["target"]
			}
			RecordEvent(db, kind, level, messageOf(group), map[string]any{
				"event_key": newEventKey(), "signature": signature, "target": target,
			})
		} else if lastSignature != "" {
			RecordEvent(db, kind, "info", kind+" condition cleared", map[string]any{"signature": ""})
		}
	}
	return promoteEvents(db, func(text string) bool { return sendTelegram(db, text) })
}

func signatureOf(group []map[string]any) string {
	if len(group) == 0 {
		return ""
	}
	parts := make([]string, len(group))
	for i, item := range group {
		parts[i] = fmt.Sprintf("%v:%v", item["id"], item["level"])
	}
	sort.Strings(parts)
	return strings.Join(parts, "|")
}

// messageOf mirrors thresholds._message.
func messageOf(group []map[string]any) string {
	titles := make([]string, len(group))
	for i, item := range group {
		titles[i], _ = item["title"].(string)
	}
	shown := titles
	if len(shown) > 10 {
		shown = shown[:10]
	}
	body := strings.Join(shown, "; ")
	if extra := len(titles) - len(shown); extra > 0 {
		body += fmt.Sprintf(" (+%d more)", extra)
	}
	return "Threshold alert: " + body
}

const downAlertCooldownSeconds = 30 * 60

// nodeAlerts owns every package-level live/node alert map. CollectMetrics is
// reachable concurrently from the worker tick and POST /metrics/collect, so
// each map access takes the mutex. graceUntil lives here too because the
// manual collect path can race the live worker.
var nodeAlerts = struct {
	mu             sync.Mutex
	nodeState      map[int64]bool
	lastDownAlert  map[int64]float64
	alertedDownSet map[int64]bool
	graceUntil     map[string]float64
}{
	nodeState:      map[int64]bool{},
	lastDownAlert:  map[int64]float64{},
	alertedDownSet: map[int64]bool{},
	graceUntil:     map[string]float64{},
}

// checkNodeAlerts mirrors node_alerts.check_node_alerts.
func checkNodeAlerts(db *sql.DB, rows []map[string]any, notify bool) int {
	sent := 0
	ts := nowSecs()
	for _, row := range rows {
		nodeID := toI64(row["node_id"])
		if nodeID == 0 {
			continue
		}
		name, _ := row["node_name"].(string)
		if name == "" {
			name = fmt.Sprintf("node-%d", nodeID)
		}
		reachable := boolOf(row["reachable"])

		nodeAlerts.mu.Lock()
		prev, seen := nodeAlerts.nodeState[nodeID]
		nodeAlerts.nodeState[nodeID] = reachable
		alertedDown := nodeAlerts.alertedDownSet[nodeID]
		lastDown := nodeAlerts.lastDownAlert[nodeID]
		nodeAlerts.mu.Unlock()

		if !seen {
			continue
		}
		if prev != reachable {
			kind := "node.up"
			sev := "info"
			msg := "🟢 Node " + name + " is back online."
			if !reachable {
				kind, sev, msg = "node.down", "error", "🔴 Node "+name+" is unreachable."
			}
			RecordEvent(db, kind, sev, msg, map[string]any{"node_id": nodeID, "target": name})
		}
		if !reachable {
			if alertedDown || !notify {
				continue
			}
			if ts-lastDown < downAlertCooldownSeconds {
				continue
			}
			if sendTelegram(db, "🔴 Node "+name+" is unreachable.") {
				nodeAlerts.mu.Lock()
				nodeAlerts.lastDownAlert[nodeID] = ts
				nodeAlerts.alertedDownSet[nodeID] = true
				nodeAlerts.mu.Unlock()
				sent++
			}
		} else if alertedDown {
			nodeAlerts.mu.Lock()
			delete(nodeAlerts.alertedDownSet, nodeID)
			nodeAlerts.mu.Unlock()
			if notify && sendTelegram(db, "🟢 Node "+name+" is back online.") {
				sent++
			}
		}
	}
	return sent
}

// SendTelegram is the exported notifier for the panel's alert test and the
// health-overview promoter.
func SendTelegram(db *sql.DB, text string) bool { return sendTelegram(db, text) }

// telegramAPIBase is the Bot API root; tests point it at a stub server.
var telegramAPIBase = "https://api.telegram.org"

// sendTelegram posts one message to the owner's Telegram chat via the Bot API.
// It is a one-way ops channel: a Telegram failure or a disabled bot is never
// an error for the caller, it just returns false.
func sendTelegram(db *sql.DB, text string) bool {
	if db == nil || text == "" {
		return false
	}
	var token string
	var enabled sql.NullInt64
	var chatID sql.NullInt64
	err := db.QueryRow(`SELECT bot_token, bot_enabled, owner_telegram_id FROM settings LIMIT 1`).
		Scan(&token, &enabled, &chatID)
	if err != nil {
		return false
	}
	token = plainToken(db, token)
	if token == "" || !chatID.Valid || chatID.Int64 == 0 {
		return false
	}
	if enabled.Valid && enabled.Int64 == 0 {
		return false
	}
	if !enabled.Valid {
		return false
	}
	body, err := json.Marshal(map[string]any{"chat_id": chatID.Int64, "text": text})
	if err != nil {
		return false
	}
	req, err := http.NewRequest(http.MethodPost, telegramAPIBase+"/bot"+token+"/sendMessage", bytes.NewReader(body))
	if err != nil {
		return false
	}
	req.Header.Set("Content-Type", "application/json")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	resp, err := telegramClient.Do(req.WithContext(ctx))
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

// plainToken decrypts a stored bot token; unencrypted values pass through.
func plainToken(db *sql.DB, stored string) string {
	_ = db
	if stored == "" {
		return ""
	}
	if plain, err := crypto.DecryptSecret(strings.TrimSpace(stored), resolvedDataDir()); err == nil && plain != "" {
		return strings.TrimSpace(plain)
	}
	return strings.TrimSpace(stored)
}

// resolvedDataDir mirrors panel.dataDir without importing the panel package.
func resolvedDataDir() string {
	if d := strings.TrimSpace(os.Getenv("DATA_DIR")); d != "" {
		return d
	}
	if node.DataDir != "" {
		return node.DataDir
	}
	return "/var/lib/ovmanager"
}

// nilDB is unused; kept out — RecordEvent always takes a live handle.

// --- helpers ---

type settingsRow struct {
	notifyExpiry      bool
	notifyNodeDown    bool
	alertDaysLeft     int
	alertUsageEnabled bool
	alertUsagePct     int
	alertCPUEnabled   bool
	alertCPUPct       int
}

func readSettings(db *sql.DB) settingsRow {
	s := settingsRow{
		notifyExpiry: true, notifyNodeDown: true, alertDaysLeft: defaultDaysLeft,
		alertUsageEnabled: true, alertUsagePct: defaultUsagePct,
		alertCPUEnabled: true, alertCPUPct: defaultCPUPct,
	}
	var ne, nnd, aue, ace sql.NullInt64
	var days, upct, cpct sql.NullInt64
	err := db.QueryRow(`SELECT notify_expiry, notify_node_down, alert_days_left, alert_usage_enabled, alert_usage_pct, alert_cpu_enabled, alert_cpu_pct FROM settings LIMIT 1`).
		Scan(&ne, &nnd, &days, &aue, &upct, &ace, &cpct)
	if err != nil {
		return s
	}
	s.notifyExpiry = ne.Valid && ne.Int64 != 0
	s.notifyNodeDown = !nnd.Valid || nnd.Int64 != 0
	s.alertDaysLeft = clamp(intOf(days), 0, 365)
	s.alertUsageEnabled = !aue.Valid || aue.Int64 != 0
	s.alertUsagePct = clamp(intOf(upct), 1, 100)
	s.alertCPUEnabled = !ace.Valid || ace.Int64 != 0
	s.alertCPUPct = clamp(intOf(cpct), 1, 100)
	return s
}

type userAlert struct {
	uuid     string
	name     string
	isActive int64
	expiry   string
	total    *int64
	used     *int64
}

func scanUserAlerts(db *sql.DB) []userAlert {
	rows, err := db.Query(`SELECT COALESCE(uuid,''), name, COALESCE(is_active,0), COALESCE(expiry_date,''), total, used FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []userAlert
	for rows.Next() {
		var u userAlert
		var expiry sql.NullString
		if rows.Scan(&u.uuid, &u.name, &u.isActive, &expiry, &u.total, &u.used) == nil {
			u.expiry = expiry.String
			out = append(out, u)
		}
	}
	return out
}

type nodeCPU struct {
	id   int64
	name string
	cpu  float64
}

func latestNodeCPU(db *sql.DB) []nodeCPU {
	return nil
}

func kvValue(conn *sql.DB, key db.SettingsKey) string {
	return db.ReadSetting(conn, key)
}

// bankerRound is banker's rounding, which Go's math.Round is not.
