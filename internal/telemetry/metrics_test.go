// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

// TrafficStat.ts is the primary key. The insert used to sit inside the node
// loop with one shared timestamp, so a fleet kept only the first row; with no
// reachable node it wrote nothing at all.
func TestCollectMetricsWritesOneTrafficRow(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}

	CollectMetrics(conn)

	var rows int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM TrafficStat`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 1 {
		t.Fatalf("TrafficStat rows = %d, want 1", rows)
	}
}
