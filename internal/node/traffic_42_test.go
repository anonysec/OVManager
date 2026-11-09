package node

import "testing"

// A user named "42" and the user with numeric id 42 are distinct rows.
// Node keys are numeric ids, so both are billed with no ambiguity.
func TestNumericNameAndNumericIDBothBilled(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	// id 42 = "alice", id 7 = "42"
	seedTrafficUser(t, conn, 42, "alice", "0", `{}`)
	seedTrafficUser(t, conn, 7, "42", "0", `{}`)
	srv.set(map[string]any{"42": int64(1000), "7": int64(2000)}, nil)
	res := SyncTraffic(conn)
	// first poll seeds both, bills nothing
	if res.BytesBilled != 0 {
		t.Fatalf("first poll billed=%d, want 0 (seed)", res.BytesBilled)
	}
	srv.set(map[string]any{"42": int64(1100), "7": int64(2300)}, nil)
	res = SyncTraffic(conn)
	if res.BytesBilled != 400 {
		t.Fatalf("billed=%d, want 400 (100 + 300)", res.BytesBilled)
	}
	if got := userUsed(t, conn, 42); got != 100 {
		t.Fatalf("alice(id 42) used=%d, want 100", got)
	}
	if got := userUsed(t, conn, 7); got != 300 {
		t.Fatalf("user named 42 (id 7) used=%d, want 300", got)
	}
}
