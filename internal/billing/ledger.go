// All accounting is integer bytes; there is no fractional currency anywhere in
// the ledger, so exactness comes from int64 arithmetic (no decimal type).
package billing

import (
	"database/sql"
	"encoding/json"
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

// LedgerRow is one traffic_ledger insert (usage.write_ledger_batch).
type LedgerRow struct {
	UserID     int64
	TS         float64
	NodeID     string
	Kind       string
	DeltaBytes int64
	MetaJSON   string
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
		`INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (?, ?, ?)
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
	if rows, err := db.Query(`SELECT day, bytes FROM user_traffic_daily WHERE user_id = ? AND day >= ?`, userID, wanted[0]); err == nil {
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
		`SELECT u.name, SUM(d.bytes) AS b FROM user_traffic_daily d
		 JOIN users u ON u.id = d.user_id WHERE d.day >= ? GROUP BY u.name ORDER BY b DESC LIMIT ?`,
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
	res, err := db.Exec(`DELETE FROM user_traffic_daily WHERE day < ?`, cutoff)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

// PruneLedger deletes ledger rows older than keep_days in LIMIT batches.
func PruneLedger(db *sql.DB, keepDays, batch int) int {
	cutoff := float64(time.Now().Unix()) - float64(clamp(keepDays, 1, 1<<30))*86400
	batch = clamp(batch, 1, 1<<30)
	total := 0
	for {
		res, err := db.Exec(
			`DELETE FROM traffic_ledger WHERE id IN (SELECT id FROM traffic_ledger WHERE ts < ? LIMIT ?)`,
			cutoff, batch,
		)
		if err != nil {
			break
		}
		removed, _ := res.RowsAffected()
		total += int(removed)
		if int(removed) < batch {
			break
		}
	}
	return total
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

// ResolveSessionUsername resolves a node-reported common name (numeric
// panel user id) through idToName. Node keys are numeric ids only, so direct
// lookup is the full semantics; a user named "42" is a different row.
func ResolveSessionUsername(clientName, nodeName string, idToName map[string]string, known map[string]bool) string {
	if mapped, ok := idToName[clientName]; ok {
		return mapped
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
		`UPDATE users SET used = ?, node_usage = ? WHERE id = ? AND COALESCE(used,0) IS ? AND COALESCE(node_usage,'{}') IS ?`,
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
