// Step 0 safety-net fixtures: recorded GET /sync/usage poll sequences
// (totals + totals_epochs) asserting final users.used with CURRENT code.
// Must pass before and after the UserNodeUsage migration.
package node

import "testing"

// Reset: counter drops to zero then climbs.
// Uses legacy username keys (current code maps by name).
func TestFixtureReset(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "1", "0", `{"1":100}`)
	polls := []struct {
		total int64
		epoch string
	}{{120, "e1"}, {0, "e2"}, {50, "e2"}, {60, "e2"}}
	want := []int64{20, 0, 50, 10}
	for i, p := range polls {
		srv.set(map[string]any{"1": p.total}, map[string]string{"1": p.epoch})
		if got := SyncTraffic(conn).BytesBilled; got != want[i] {
			t.Fatalf("reset poll %d billed=%d want %d", i, got, want[i])
		}
	}
	if got := userUsed(t, conn, 1); got != 80 {
		t.Fatalf("reset used=%d want 80", got)
	}
}

// Epoch change: epoch bump re-seeds baseline without re-billing the delta.
func TestFixtureEpochChange(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "1", "0", `{}`)
	srv.set(map[string]any{"1": int64(200)}, map[string]string{"1": "e1"})
	_ = SyncTraffic(conn)
	srv.set(map[string]any{"1": int64(9999)}, map[string]string{"1": "e2"})
	if got := SyncTraffic(conn).BytesBilled; got != 0 {
		t.Fatalf("epoch change billed=%d want 0", got)
	}
	srv.set(map[string]any{"1": int64(10009)}, map[string]string{"1": "e2"})
	if got := SyncTraffic(conn).BytesBilled; got != 10 {
		t.Fatalf("post-epoch billed=%d want 10", got)
	}
	if got := userUsed(t, conn, 1); got != 10 {
		t.Fatalf("epoch used=%d want 10", got)
	}
}

// Reseed marker: admin reset seeds all node baselines without re-billing.
func TestFixtureReseed(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "1", "100", `{"1":1000,"__reseed":true}`)
	srv.set(map[string]any{"1": int64(1000)}, nil)
	if got := SyncTraffic(conn).BytesBilled; got != 0 {
		t.Fatalf("reseed billed=%d want 0", got)
	}
	srv.set(map[string]any{"1": int64(1015)}, nil)
	if got := SyncTraffic(conn).BytesBilled; got != 15 {
		t.Fatalf("post-reseed billed=%d want 15", got)
	}
	if got := userUsed(t, conn, 1); got != 115 {
		t.Fatalf("reseed used=%d want 115", got)
	}
}

// Node offline: node stops answering, then returns with higher counter.
func TestFixtureNodeOffline(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "1", "0", `{"1":100}`)
	srv.set(map[string]any{}, nil) // offline: totals empty
	if got := SyncTraffic(conn).BytesBilled; got != 0 {
		t.Fatalf("offline billed=%d want 0", got)
	}
	srv.set(map[string]any{"1": int64(150)}, nil)
	if got := SyncTraffic(conn).BytesBilled; got != 50 {
		t.Fatalf("back online billed=%d want 50", got)
	}
	if got := userUsed(t, conn, 1); got != 50 {
		t.Fatalf("offline used=%d want 50", got)
	}
}
