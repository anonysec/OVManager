// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func TestLatestNodeCPUReadsTheNewestSample(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO Node (id, name, address, port, key) VALUES (1, 'n1', '1.2.3.4', 2083, 'k')`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO NodeStat (node_id, created_at, cpu) VALUES (1, 100, 10), (1, 200, 91)`); err != nil {
		t.Fatal(err)
	}

	got := latestNodeCPU(conn)
	if len(got) != 1 || got[0].cpu != 91 {
		t.Fatalf("latestNodeCPU = %+v, want one node at 91%%", got)
	}
}
