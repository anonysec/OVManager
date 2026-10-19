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
	"sort"
	"strings"
	"time"
)

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

// WriteLedgerBatch inserts ledger rows sorted by (user_id, node_id).
func WriteLedgerBatch(db *sql.DB, rows []LedgerRow) int {
	if len(rows) == 0 {
		return 0
	}
	ordered := append([]LedgerRow{}, rows...)
	sort.SliceStable(ordered, func(i, j int) bool {
		if ordered[i].UserID != ordered[j].UserID {
			return ordered[i].UserID < ordered[j].UserID
		}
		return ordered[i].NodeID < ordered[j].NodeID
	})
	for _, r := range ordered {
		meta := r.MetaJSON
		if meta == "" {
			meta = "{}"
		}
		_, _ = db.Exec(
			`INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes, meta_json) VALUES (?, ?, ?, ?, ?, ?)`,
			r.UserID, r.TS, r.NodeID, r.Kind, r.DeltaBytes, meta,
		)
	}
	return len(ordered)
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
		rows.Close()
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

// --- pure helpers (daily.py) ---

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

// ComputeSessionDelta returns (delta_bytes, new_state) for one user on one node.
//
// new_state is a map[string]int64 when the node reports per-session data, or an
// int64 legacy total otherwise (mirrors the union return).
func ComputeSessionDelta(sessions map[string]any, prevState any, legacyTotal float64) (int, any) {
	if sessions != nil {
		if prev, ok := prevState.(map[string]any); ok {
			delta := 0
			for skey, cur := range sessions {
				last := int64(0)
				if lv, ok := prev[skey]; ok {
					last = toI64(lv)
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
		prevInt := int64(0)
		if prevState != nil {
			if _, isDict := prevState.(map[string]any); !isDict {
				prevInt = toI64(prevState)
			}
		}
		curTotal := int64(0)
		for _, v := range sessions {
			curTotal += toI64(v)
		}
		delta := 0
		if curTotal >= prevInt {
			delta = int(curTotal - prevInt)
		} else {
			delta = int(curTotal)
		}
		return delta, intMap(sessions)
	}
	prevInt := int64(0)
	if prevState != nil {
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
		`UPDATE users SET used = ?, node_usage = ? WHERE id = ? AND used IS ? AND node_usage IS ?`,
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
