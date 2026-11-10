// All accounting is integer bytes; there is no fractional currency anywhere in
// the ledger, so exactness comes from int64 arithmetic (no decimal type).
package billing

import (
	"database/sql"
	"encoding/json"
	"strings"
	"time"
)

// NodeUsageVersion is the current schema version for node_usage JSON.
// v1: flat map with int64 values (legacy)
// v2: {"version": 2, "data": {"node_id": {"total": int64}}}
const NodeUsageVersion = 2

// Execer is the slice of *sql.DB the writers use; *sql.Tx satisfies it too,
// so a user write and its daily row can share one transaction.
type Execer interface {
	Exec(query string, args ...any) (sql.Result, error)
}

// today renders the UTC date key used by user_traffic_daily.
func today() string { return time.Now().UTC().Format("2006-01-02") }

// RecordDailyBytes adds billed bytes to a user's day row (usage.record_daily_bytes).
func RecordDailyBytes(db Execer, userID, delta int64, day string) {
	if delta <= 0 {
		return
	}
	if day == "" {
		day = today()
	}
	_, _ = db.Exec(
		`INSERT INTO UserTrafficDaily (user_id, day, bytes) VALUES (?, ?, ?)
		 ON CONFLICT(user_id, day) DO UPDATE SET bytes = bytes + ?`,
		userID, day, delta, delta,
	)
}

// UserDailySeries returns the last N UTC days for one user, oldest first, zero-filled.
func UserDailySeries(db *sql.DB, userID int64, days int) []map[string]any {
	days = clamp(days, 1, 90)
	now := time.Now().UTC()
	wanted := make([]string, 0, days)
	for i := days - 1; i >= 0; i-- {
		wanted = append(wanted, now.AddDate(0, 0, -i).Format("2006-01-02"))
	}
	have := map[string]int64{}
	if rows, err := db.Query(`SELECT day, bytes FROM UserTrafficDaily WHERE user_id = ? AND day >= ?`, userID, wanted[0]); err == nil {
		for rows.Next() {
			var day string
			var bytes int64
			if rows.Scan(&day, &bytes) == nil {
				have[day] = bytes
			}
		}
		_ = rows.Close()
	}
	out := make([]map[string]any, 0, days)
	for _, d := range wanted {
		out = append(out, map[string]any{"day": d, "bytes": have[d]})
	}
	return out
}

// TopUsers returns the top users by billed bytes over the last N days.
func TopUsers(db *sql.DB, days, limit int) []map[string]any {
	days = clamp(days, 1, 90)
	limit = clamp(limit, 1, 25)
	start := time.Now().UTC().AddDate(0, 0, -(days - 1)).Format("2006-01-02")
	rows, err := db.Query(
		`SELECT u.name, SUM(d.bytes) AS b FROM UserTrafficDaily d
		 JOIN User u ON u.id = d.user_id WHERE d.day >= ? GROUP BY u.name ORDER BY b DESC LIMIT ?`,
		start, limit,
	)
	if err != nil {
		return []map[string]any{}
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var name string
		var bytes int64
		if rows.Scan(&name, &bytes) == nil {
			out = append(out, map[string]any{"name": name, "bytes": bytes})
		}
	}
	return out
}

// PruneDaily deletes daily rows older than keep_days.
func PruneDaily(db *sql.DB, keepDays int) int {
	cutoff := time.Now().UTC().AddDate(0, 0, -clamp(keepDays, 1, 1<<30)).Format("2006-01-02")
	res, err := db.Exec(`DELETE FROM UserTrafficDaily WHERE day < ?`, cutoff)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

// --- pure helpers (daily) ---

// Canon renders the canonical node_usage text both sides of an OCC compare speak.
//
// default-str fallback for exotic types is not reproduced.
func Canon(state any) string {
	if s, ok := state.(string); ok {
		if s == "" {
			return "{}"
		}
		var parsed any
		if json.Unmarshal([]byte(s), &parsed) != nil {
			return s
		}
		return compact(parsed)
	}
	return compact(state)
}

func compact(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}

func ResolveSessionUsername(clientName, nodeName string, idToName map[string]string, known map[string]bool) string {
	username := extractUsername(clientName, nodeName, known)
	if known != nil && known[username] {
		return username
	}
	if mapped, ok := idToName[username]; ok {
		return mapped
	}
	return username
}

func extractUsername(clientName, nodeName string, known map[string]bool) string {
	if known != nil && known[clientName] {
		return clientName
	}
	if nodeName != "" {
		suffix := "-" + nodeName
		if strings.HasSuffix(clientName, suffix) && len(clientName) > len(suffix) {
			return clientName[:len(clientName)-len(suffix)]
		}
	}
	return clientName
}

// ComputeTotalDelta applies the D5 rule for one node's cumulative counter.
//
// current is the node's reported total, previous the held baseline. explicitReset
// is true when a reseed or an epoch change makes the current value a fresh
// baseline. It returns the bytes to bill and the baseline to persist: an
// unexplained decrease holds the previous baseline instead of the lower
// current value.
func ComputeTotalDelta(current, previous int64, explicitReset bool) (delta, baseline int64) {
	if explicitReset {
		return 0, current
	}
	if current >= previous {
		return current - previous, current
	}
	return 0, previous
}

// ApplyUserTraffic persists one user's traffic only if the row still holds the
// loaded values (daily._apply_user_traffic). Returns false on an OCC miss.
func ApplyUserTraffic(db Execer, userID int64, expectedUsed int64, expectedState string, newUsed int64, newState string, delta int64) bool {
	res, err := db.Exec(
		`UPDATE User SET used = ?, node_usage = ? WHERE id = ? AND COALESCE(used,0) IS ? AND COALESCE(node_usage,'{}') IS ?`,
		newUsed, newState, userID, expectedUsed, expectedState,
	)
	if err != nil {
		return false
	}
	n, _ := res.RowsAffected()
	if n != 1 {
		return false
	}
	if delta != 0 {
		RecordDailyBytes(db, userID, delta, "")
	}
	return true
}

func clamp(v, low, high int) int {
	if v < low {
		return low
	}
	if v > high {
		return high
	}
	return v
}
