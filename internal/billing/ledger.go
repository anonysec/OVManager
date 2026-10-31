// Package billing ports backend/operations/billing: the per-user daily traffic
// history and the traffic ledger (usage.py + the DB half of daily.py).
//
// All accounting is integer bytes; there is no fractional currency anywhere in
// the ledger, so exactness comes from int64 arithmetic (no decimal type).
package billing

import (
	"database/sql"
	"encoding/json"
	"fmt"
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
// ponytail: only handles the shapes daily.py stores (object or its JSON text);
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

// ExtractUsername resolves a node-reported key to a panel username.
func ExtractUsername(clientName, nodeName string, known map[string]bool) string {
	if known != nil && known[clientName] {
		return clientName
	}
	suffix := "-" + nodeName
	if strings.HasSuffix(clientName, suffix) {
		return clientName[:len(clientName)-len(suffix)]
	}
	return clientName
}

// ResolveSessionUsername resolves a node-reported common name through the
// optional numeric-ID map. A known username (including its node-suffix-stripped
// form) takes precedence over an identical numeric ID string; without this
// check, a user named "42" could be reported as the unrelated row whose ID is 42.
func ResolveSessionUsername(clientName, nodeName string, idToName map[string]string, known map[string]bool) string {
	username := ExtractUsername(clientName, nodeName, known)
	if known != nil && known[username] {
		return username
	}
	if mapped, ok := idToName[username]; ok {
		return mapped
	}
	return username
}

// extractNodeUsageData extracts the "data" map from a versioned node_usage state.
// Returns nil if the state is not a valid versioned format.
func extractNodeUsageData(state any) map[string]map[string]int64 {
	if state == nil {
		return nil
	}
	// If state is a string, parse it first
	var parsed any
	switch s := state.(type) {
	case string:
		if err := json.Unmarshal([]byte(s), &parsed); err != nil {
			return nil
		}
	case map[string]any:
		parsed = s
	default:
		return nil
	}

	m, ok := parsed.(map[string]any)
	if !ok {
		return nil
	}

	// Check for versioned format
	if v, ok := m["version"]; ok {
		if f, ok := v.(float64); ok && int(f) >= NodeUsageVersion {
			if data, ok := m["data"].(map[string]any); ok {
				result := make(map[string]map[string]int64)
				for k, v := range data {
					if sub, ok := v.(map[string]any); ok {
						if total, ok := sub["total"].(float64); ok {
							result[k] = map[string]int64{"total": int64(total)}
						}
					}
				}
				return result
			}
		}
	}
	// Legacy flat map format
	result := make(map[string]map[string]int64)
	for k, v := range m {
		if k == "version" || k == "data" {
			continue
		}
		total := int64(0)
		if num, ok := v.(float64); ok {
			total = int64(num)
		} else if sub, ok := v.(map[string]any); ok {
			if t, ok := sub["total"]; ok {
				if n, ok := t.(float64); ok {
					total = int64(n)
				}
			}
		}
		if total > 0 {
			result[k] = map[string]int64{"total": total}
		}
	}
	return result
}

// ComputeSessionDelta returns (delta_bytes, new_state) for one user on one node.
//
// new_state is a map[string]int64 when the node reports per-session data, or an
// int64 legacy total otherwise (mirrors the union return).
func ComputeSessionDelta(sessions map[string]any, prevState any, legacyTotal float64) (int, any) {
	if sessions != nil {
		// Extract previous state data map
		prevData := extractNodeUsageData(prevState)
		delta := 0
		for skey, cur := range sessions {
			last := int64(0)
			if prevData != nil {
				if sub, ok := prevData[skey]; ok {
					last = sub["total"]
				}
			}
			curInt := toI64(cur)
			if curInt >= last {
				delta += int(curInt - last)
			} else {
				delta += int(curInt)
			}
		}
		return delta, intMap(sessions)
	}
	// sessions is nil: legacy behavior returns integer total, not a map
	prevData := extractNodeUsageData(prevState)
	prevInt := int64(0)
	if prevData != nil {
		// Sum all totals from previous data
		for _, sub := range prevData {
			prevInt += sub["total"]
		}
	} else if prevState != nil {
		if _, isDict := prevState.(map[string]any); !isDict {
			prevInt = toI64(prevState)
		}
	}
	curTotal := int64(legacyTotal)
	delta := 0
	if curTotal >= prevInt {
		delta = int(curTotal - prevInt)
	} else {
		delta = int(curTotal)
	}
	return delta, curTotal
}

func intMap(m map[string]any) map[string]int64 {
	out := make(map[string]int64, len(m))
	for k, v := range m {
		out[k] = toI64(v)
	}
	return out
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

func toI64(v any) int64 {
	switch n := v.(type) {
	case float64:
		return int64(n)
	case int:
		return int64(n)
	case int64:
		return n
	case json.Number:
		i, _ := n.Int64()
		return i
	case string:
		var i int64
		_, _ = fmt.Sscanf(n, "%d", &i)
		return i
	}
	return 0
}
