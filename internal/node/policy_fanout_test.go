package node

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// TestReconcileAppliesBeyondFanoutLimit: with more jobs than the fan-out
// semaphore cap (20), a single shared deadline would starve the queued
// calls even when the node is healthy. Chunked fan-out must apply all.
func TestReconcileAppliesBeyondFanoutLimit(t *testing.T) {
	conn := newTrafficDB(t)
	var puts atomic.Int64
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/user", func(w http.ResponseWriter, r *http.Request) {
		puts.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true}`))
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	seedTrafficNode(t, conn, 1, "node-a", srv)
	const users = 25
	for i := int64(0); i < users; i++ {
		if _, err := conn.Exec(`INSERT INTO User (id, uuid, name, max_logins, is_active) VALUES (?, ?, ?, 3, 1)`,
			1000+i, "u", fmt.Sprintf("user%02d", i)); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}
	res := ReconcileUserPolicies(conn, time.Now(), true)
	if res.Failed != 0 {
		t.Fatalf("healthy node: %d jobs failed (%v), want all %d applied", res.Failed, res.Failures, users)
	}
	if puts.Load() != users {
		t.Fatalf("node received %d policy PUTs, want %d", puts.Load(), users)
	}
	if res.Applied != users {
		t.Fatalf("applied = %d, want %d", res.Applied, users)
	}
	// Hashes recorded: a non-forced pass must skip everything.
	res2 := ReconcileUserPolicies(conn, time.Now(), false)
	if res2.Skipped != users {
		t.Fatalf("non-forced pass skipped = %d, want %d (hashes not recorded)", res2.Skipped, users)
	}
}
