// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

// A deleted node's baselines must go with it: node ids are reused, and a
// stale baseline would bill the next node from the old total.
func TestDeleteNodeDropsTrafficBaselines(t *testing.T) {
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO Node (id, name, address, port, key) VALUES (7, 'n7', '1.2.3.4', 2083, 'k')`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO UserNodeUsage (user_id, node_id, baseline, epoch) VALUES (1, 7, 700, 'e')`); err != nil {
		t.Fatal(err)
	}

	if !DeleteNodeHandler(7, conn) {
		t.Fatal("DeleteNodeHandler = false")
	}
	var count int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM UserNodeUsage WHERE node_id = 7`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 0 {
		t.Fatalf("baselines left for the deleted node: %d", count)
	}
}
