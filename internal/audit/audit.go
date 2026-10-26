// Package audit writes the panel's audit trail: one row per state-changing
// operation, attributed to the actor who performed it.
//
// It is a leaf package (stdlib + a *sql.DB) so that every layer can write
// audit rows without importing a sibling: internal/telemetry imports
// internal/node, so internal/node cannot import internal/telemetry.
//
// The stored detail keeps the shape the rest of the tree already expects:
// {"severity": ..., "message": ..., "meta": {...}}. The event promoter in
// internal/telemetry reads meta.event_key to decide what to send to Telegram,
// and the audit prune removes rows that carry NO event_key — so an audit row
// (which has no event_key) is never messaged and is always prunable.
package audit

import (
	"database/sql"
	"encoding/json"
	"strings"
	"time"
)

// Record writes one audit row. actor is the authenticated username; an empty
// actor is stored as "system". meta must never carry a secret (no password, no
// token, no certificate body) — the detail column is rendered as text in the
// panel and is readable by anyone who can read the activity page.
func Record(db *sql.DB, actor, kind, severity, message string, meta map[string]any) {
	if db == nil {
		return
	}
	if meta == nil {
		meta = map[string]any{}
	}
	payload := map[string]any{"severity": severity, "message": message, "meta": meta}
	detail, err := json.Marshal(payload)
	if err != nil {
		return
	}
	var target any
	if t, ok := meta["target"].(string); ok && t != "" {
		target = t
	}
	who := strings.TrimSpace(actor)
	if who == "" {
		who = "system"
	}
	_, _ = db.Exec(`INSERT INTO audit_logs (ts, actor, action, target, detail) VALUES (?, ?, ?, ?, ?)`,
		float64(time.Now().Unix()), who, kind, target, string(detail))
}
