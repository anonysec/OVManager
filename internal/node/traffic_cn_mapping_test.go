// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import "testing"

// A panel rebuilt from scratch gives users new ids while the node still holds
// certificates whose CN is the username (or an old numeric alias). Billing must
// resolve those CNs by name, not drop them: this is the "everything bills 0"
// failure seen after a panel reset.
func TestSyncTrafficResolvesUsernameCN(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 2, "winston", "0", `{}`)
	seedTrafficUser(t, conn, 3, "414", "0", `{}`)
	seedTrafficUser(t, conn, 4, "417", "0", `{}`)

	// First pass seeds every baseline (delta 0); the unknown CN is ignored.
	srv.set(map[string]any{
		"winston": int64(1000),
		"414":     int64(500),
		"999":     int64(7),
	}, map[string]string{"winston": "e1", "414": "e1", "999": "e1"})
	if got := SyncTraffic(conn).BytesBilled; got != 0 {
		t.Fatalf("seed pass billed %d bytes, want 0", got)
	}

	// Second pass bills the deltas to the right usernames.
	srv.set(map[string]any{
		"winston": int64(1100),
		"414":     int64(700),
		"999":     int64(9),
	}, map[string]string{"winston": "e1", "414": "e1", "999": "e1"})
	res := SyncTraffic(conn)
	if res.BytesBilled != 300 {
		t.Fatalf("billed %d bytes, want 300", res.BytesBilled)
	}
	if got := userUsed(t, conn, 2); got != 100 {
		t.Fatalf("winston used=%d, want 100", got)
	}
	if got := userUsed(t, conn, 3); got != 200 {
		t.Fatalf("414 used=%d, want 200", got)
	}
	if got := userUsed(t, conn, 4); got != 0 {
		t.Fatalf("417 used=%d, want 0 (no CN reported)", got)
	}
}

// A numeric CN always means the user id, even when another user's username is
// that same number: the id key is registered unconditionally and wins.
func TestSyncTrafficIDBeatsUsernameCollision(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 5, "3", "0", `{}`) // username looks like an id
	seedTrafficUser(t, conn, 3, "amy", "0", `{}`)

	srv.set(map[string]any{"3": int64(100)}, map[string]string{"3": "e1"})
	_ = SyncTraffic(conn)
	srv.set(map[string]any{"3": int64(150)}, map[string]string{"3": "e1"})
	if got := SyncTraffic(conn).BytesBilled; got != 50 {
		t.Fatalf("billed %d, want 50", got)
	}
	if got := userUsed(t, conn, 3); got != 50 {
		t.Fatalf("id 3 used=%d, want 50 (numeric CN is the id)", got)
	}
	if got := userUsed(t, conn, 5); got != 0 {
		t.Fatalf("user named \"3\" used=%d, want 0", got)
	}
}
