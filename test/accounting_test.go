package tests

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/accounting"
)

type golden struct {
	Canon   [][2]any `json:"canon"`
	PyRound [][2]any `json:"py_round"`
}

func loadGolden(t *testing.T) golden {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", "accounting_golden.json"))
	if err != nil {
		t.Fatalf("golden: %v", err)
	}
	var g golden
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatalf("golden decode: %v", err)
	}
	return g
}

func TestAccountingCanonGolden(t *testing.T) {
	for _, tc := range loadGolden(t).Canon {
		got := accounting.Canon(tc[0])
		if got != tc[1].(string) {
		}
	}
}

func TestDailyBytesUpsertAndSeries(t *testing.T) {
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO User (id, uuid, name) VALUES (1,'u1','ann')`); err != nil {
		t.Fatalf("seed user: %v", err)
	}
	accounting.RecordDailyBytes(conn, 1, 100, "")
	accounting.RecordDailyBytes(conn, 1, 50, "")
	var bytes int64
	if err := conn.QueryRow(`SELECT bytes FROM UserTrafficDaily WHERE user_id = 1`).Scan(&bytes); err != nil {
		t.Fatalf("read daily: %v", err)
	}
	if bytes != 150 {
		t.Fatalf("daily bytes = %d, want 150", bytes)
	}

	series := accounting.UserDailySeries(conn, 1, 3)
	if len(series) != 3 {
		t.Fatalf("series len = %d, want 3", len(series))
	}
	if series[2]["bytes"].(int64) != 150 || series[0]["bytes"].(int64) != 0 {
		t.Fatalf("series = %v", series)
	}

	top := accounting.TopUsers(conn, 7, 5)
	if len(top) != 1 || top[0]["name"] != "ann" || top[0]["bytes"].(int64) != 150 {
	}
}
