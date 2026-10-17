// Billing ledger parity: golden outputs generated from the real Python module
// (see testdata/billing_golden.json) plus DB-level ordering/upsert behaviour.
package tests

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"ovmanager-go/internal/billing"
)

type golden struct {
	Canon           [][2]any   `json:"canon"`
	ExtractUsername [][4]any   `json:"extract_username"`
	SessionDelta    [][5]any   `json:"session_delta"`
	PyRound         [][2]any   `json:"py_round"`
}

func loadGolden(t *testing.T) golden {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", "billing_golden.json"))
	if err != nil {
		t.Fatalf("golden: %v", err)
	}
	var g golden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatalf("golden decode: %v", err)
	}
	return g
}

func TestBillingCanonGolden(t *testing.T) {
	for _, tc := range loadGolden(t).Canon {
		got := billing.Canon(tc[0])
		if got != tc[1].(string) {
			t.Errorf("Canon(%v) = %q, want %q", tc[0], got, tc[1])
		}
	}
}

func TestBillingExtractUsernameGolden(t *testing.T) {
	for _, tc := range loadGolden(t).ExtractUsername {
		known := map[string]bool{}
		for _, name := range tc[2].([]any) {
			known[name.(string)] = true
		}
		got := billing.ExtractUsername(tc[0].(string), tc[1].(string), known)
		if got != tc[3].(string) {
			t.Errorf("ExtractUsername(%v,%v) = %q, want %q", tc[0], tc[1], got, tc[3])
		}
	}
}

func TestBillingSessionDeltaGolden(t *testing.T) {
	for _, tc := range loadGolden(t).SessionDelta {
		var sessions map[string]any
		if tc[0] != nil {
			sessions, _ = tc[0].(map[string]any)
		}
		delta, state := billing.ComputeSessionDelta(sessions, tc[1], numOrZero(tc[2]))
		if delta != int(numOrZero(tc[3])) {
			t.Errorf("delta(%v) = %d, want %v", tc[0], delta, tc[3])
		}
		gotState := mustJSON(t, state)
		wantState := mustJSON(t, tc[4])
		if gotState != wantState {
			t.Errorf("new_state(%v) = %s, want %s", tc[0], gotState, wantState)
		}
	}
}

func numOrZero(v any) float64 {
	f, _ := v.(float64)
	return f
}

func mustJSON(t *testing.T, v any) string {
	t.Helper()
	if m, ok := v.(map[string]int64); ok {
		conv := map[string]any{}
		for k, n := range m {
			conv[k] = n
		}
		v = conv
	}
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	return string(b)
}

func TestLedgerBatchOrdersByUserAndNode(t *testing.T) {
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("ledger schema: %v", err)
	}
	billing.WriteLedgerBatch(conn, []billing.LedgerRow{
		{UserID: 2, TS: 10, NodeID: "b", Kind: "poll", DeltaBytes: 5},
		{UserID: 1, TS: 10, NodeID: "z", Kind: "poll", DeltaBytes: 1},
		{UserID: 1, TS: 10, NodeID: "a", Kind: "poll", DeltaBytes: 2},
	})
	rows, err := conn.Query(`SELECT user_id, node_id FROM traffic_ledger ORDER BY id`)
	if err != nil {
		t.Fatalf("select: %v", err)
	}
	defer rows.Close()
	var order []string
	for rows.Next() {
		var uid int64
		var nid string
		_ = rows.Scan(&uid, &nid)
		order = append(order, string(rune('0'+uid))+nid)
	}
	want := []string{"1a", "1z", "2b"}
	if len(order) != 3 || order[0] != want[0] || order[1] != want[1] || order[2] != want[2] {
		t.Fatalf("insert order = %v, want %v", order, want)
	}
}

func TestDailyBytesUpsertAndSeries(t *testing.T) {
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name) VALUES (1,'u1','ann')`); err != nil {
		t.Fatalf("seed user: %v", err)
	}
	billing.RecordDailyBytes(conn, 1, 100, "")
	billing.RecordDailyBytes(conn, 1, 50, "")
	billing.RecordDailyBytes(conn, 1, 0, "") // zero is a no-op

	var bytes int64
	if err := conn.QueryRow(`SELECT bytes FROM user_traffic_daily WHERE user_id = 1`).Scan(&bytes); err != nil {
		t.Fatalf("read daily: %v", err)
	}
	if bytes != 150 {
		t.Fatalf("daily bytes = %d, want 150", bytes)
	}

	series := billing.UserDailySeries(conn, 1, 3)
	if len(series) != 3 {
		t.Fatalf("series len = %d, want 3", len(series))
	}
	if series[2]["bytes"].(int64) != 150 || series[0]["bytes"].(int64) != 0 {
		t.Fatalf("series = %v", series)
	}

	top := billing.TopUsers(conn, 7, 5)
	if len(top) != 1 || top[0]["name"] != "ann" || top[0]["bytes"].(int64) != 150 {
		t.Fatalf("top users = %v", top)
	}
}
