// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestDeleteThenRestoreNode(t *testing.T) {
	conn := newTrafficDB(t)
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404) })
	srv := httptest.NewTLSServer(mux)
	defer srv.Close()
	seedTrafficNode(t, conn, 7, "node-a", srv)

	if !DeleteNodeHandler(7, conn) {
		t.Fatal("DeleteNodeHandler failed")
	}
	if n := GetNodeByID(conn, 7); n != nil {
		t.Fatal("node still present after delete")
	}

	ok, msg := RestoreNodeHandler(7, conn)
	if !ok {
		t.Fatalf("restore failed: %s", msg)
	}
	got := GetNodeByID(conn, 7)
	if got == nil || got.Name != "node-a" || got.ID != 7 {
		t.Fatalf("restored = %+v, want id 7 node-a", got)
	}

	// Snapshot is consumed: a second restore must report the window gone.
	if ok, _ = RestoreNodeHandler(7, conn); ok {
		t.Fatal("second restore succeeded")
	}
}

func TestRestoreNodeExpiredWindow(t *testing.T) {
	conn := newTrafficDB(t)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404) }))
	defer srv.Close()
	seedTrafficNode(t, conn, 9, "node-b", srv)

	if !DeleteNodeHandler(9, conn) {
		t.Fatal("DeleteNodeHandler failed")
	}
	// Backdate the snapshot past the TTL.
	if _, err := conn.Exec(`UPDATE deleted_nodes SET deleted_at = ?, expires_at = ? WHERE id = 9`,
		time.Now().Add(-2*time.Minute).Unix(), time.Now().Add(-time.Minute).Unix()); err != nil {
		t.Fatalf("backdate: %v", err)
	}
	ok, _ := RestoreNodeHandler(9, conn)
	if ok {
		t.Fatal("expired restore succeeded")
	}
	var n int64
	err := conn.QueryRow(`SELECT COUNT(*) FROM deleted_nodes WHERE id = 9`).Scan(&n)
	if err != nil {
		t.Fatalf("count: %v", err)
	}
	if n != 0 {
		t.Fatalf("expired snapshot not purged: %d rows", n)
	}
}

func TestDeleteNodeSnapshotsRow(t *testing.T) {
	conn := newTrafficDB(t)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(404) }))
	defer srv.Close()
	seedTrafficNode(t, conn, 11, "node-c", srv)
	if !DeleteNodeHandler(11, conn) {
		t.Fatal("DeleteNodeHandler failed")
	}
	var snap string
	var expires float64
	err := conn.QueryRow(`SELECT snap_json, expires_at FROM deleted_nodes WHERE id = 11`).Scan(&snap, &expires)
	if err != nil {
		t.Fatalf("snapshot missing: %v", err)
	}
	if snap == "" || expires-float64(time.Now().Unix()) > 30 {
		t.Fatalf("snapshot too short: %q expires %v", snap, expires)
	}
	var _ sql.NullString
}
