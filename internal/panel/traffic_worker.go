// Per-user traffic accounting worker: a single goroutine polls
// every active node's cumulative totals and bills the deltas through
// node.SyncTraffic. Independent of the Telegram ready() gate — accounting must
// run whether or not a bot is configured.
package panel

import (
	"context"
	"database/sql"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/node"
)

// trafficBootDelay leaves the panel time to settle before the first poll.
const trafficBootDelay = 30 * time.Second

var trafficWorkerOnce sync.Once

// trafficSync is node.SyncTraffic behind a mutex-guarded seam so the worker
// test can count ticks without a live node (and stay race-clean).
var (
	trafficSyncMu sync.Mutex
	trafficSync   = node.SyncTraffic
)

func runTrafficSync(db *sql.DB) node.TrafficResult {
	trafficSyncMu.Lock()
	fn := trafficSync
	trafficSyncMu.Unlock()
	return fn(db)
}

// trafficPollSeconds is TrafficPollSeconds (default 60). A non-positive
// or unparsable value falls back to the default rather than spinning the loop.
func trafficPollSeconds() int {
	if v := strings.TrimSpace(envOrFile("TrafficPollSeconds")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return 60
}

// startTrafficWorker launches the traffic poll loop once per process.
// The once-guard is test-only (prevents duplicate loops in tests calling
// Mount repeatedly); production Mount calls it once.
func (h *Handler) startTrafficWorker() {
	trafficWorkerOnce.Do(func() {
		Run(context.Background(), []job{{
			name:  "traffic worker",
			delay: trafficBootDelay,
			every: func() time.Duration { return time.Duration(trafficPollSeconds()) * time.Second },
			fn:    func(ctx context.Context) { h.trafficTick(ctx) },
		}})
	})
}

// policyReconcileMu guards lastPolicyReconcile.
var (
	policyReconcileMu   sync.Mutex
	lastPolicyReconcile time.Time
)

// trafficTick runs one accounting pass. SwapDB-safe: h.Svc.DB() is read per
// tick, not cached.
func (h *Handler) trafficTick(ctx context.Context) {
	db := h.Svc.DB()
	res := runTrafficSync(db)
	log.Printf("traffic: polled %d node(s), failed %d, users updated %d, seeded %d, billed %d bytes",
		res.NodesPolled, res.NodesFailed, res.UsersUpdated, res.UsersSeeded, res.BytesBilled)

	now := time.Now()
	force := false
	policyReconcileMu.Lock()
	if lastPolicyReconcile.IsZero() || now.Sub(lastPolicyReconcile) >= 10*time.Minute {
		force = true
		lastPolicyReconcile = now
	}
	policyReconcileMu.Unlock()
	node.ReconcileUserPolicies(db, now, force)
	rr := node.ProcessPendingRevocations(db, 20)
	if rr.Attempted > 0 {
		log.Printf("revocations: attempted %d, acknowledged %d, failed %d",
			rr.Attempted, rr.Acknowledged, rr.Failed)
	}
}

// syncTraffic is POST /maintenance/sync-traffic: run one accounting pass now
// and return its TrafficResult envelope.
func (h *Handler) syncTraffic(w http.ResponseWriter, r *http.Request) {
	db := h.Svc.DB()
	res := runTrafficSync(db)
	envelope(w, true, "Traffic synced", res)
}
