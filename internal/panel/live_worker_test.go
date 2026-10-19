package panel

import (
	"database/sql"
	"sync/atomic"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
)

// TestLiveWorkerStarts launches the collector worker against a node-less DB
// (Mount must not panic) and verifies a manual tick reaches
// CollectLiveSnapshot. The collector itself is swapped for a counter so the
// test needs no live node.
func TestLiveWorkerStarts(t *testing.T) {
	conn, dir := newTrafficDB(t)
	h := NewHandler(auth.NewService(conn, dir))

	var calls atomic.Int32
	restore := setLiveCollect(func(*sql.DB) { calls.Add(1) })
	t.Cleanup(restore)

	h.startLiveWorker() // idempotent; must not panic
	h.liveTick()

	if got := calls.Load(); got != 1 {
		t.Fatalf("CollectLiveSnapshot calls after one tick = %d, want 1", got)
	}
}
