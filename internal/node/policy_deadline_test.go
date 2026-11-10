package node

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestReconcileBoundedByHangingNode: reconcile must return within roughly
// the fan-out deadline even when the node never answers, and must not let
// a hanging node hold the policy lock (plus every handler SyncUserPolicy
// behind it) for calls/20 × timeout.
func TestReconcileBoundedByHangingNode(t *testing.T) {
	conn := newTrafficDB(t)
	release := make(chan struct{})
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/user", func(w http.ResponseWriter, r *http.Request) {
		<-release // hangs until the test releases it, past the request deadline
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true}`))
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	t.Cleanup(func() { close(release) })
	seedTrafficNode(t, conn, 1, "hanging", srv)
	for i := int64(0); i < 5; i++ {
		if _, err := conn.Exec(`INSERT INTO User (id, uuid, name, max_logins, is_active) VALUES (?, ?, ?, 3, 1)`,
			7+i, "u", "user"+string(rune('0'+i))); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}
	start := time.Now()
	res := ReconcileUserPolicies(conn, time.Now(), true)
	elapsed := time.Since(start)
	if elapsed > 15*time.Second {
		t.Fatalf("reconcile took %s behind a hanging node, want bounded by the fan-out deadline", elapsed)
	}
	if res.Failed == 0 {
		t.Fatalf("hanging node calls should fail (deadline), result = %+v", res)
	}
	// Lock released: a second pass also returns promptly instead of queueing
	// behind the first.
	start = time.Now()
	_ = ReconcileUserPolicies(conn, time.Now(), true)
	if elapsed := time.Since(start); elapsed > 15*time.Second {
		t.Fatalf("second reconcile took %s, policy lock held too long", elapsed)
	}
}
