// Per-user traffic accounting worker (design §4.4): a single goroutine polls
// every active node's cumulative totals and bills the deltas through
// node.SyncTraffic. Independent of the Telegram ready() gate — accounting must
// run whether or not a bot is configured.
package panel

import (
	"database/sql"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// trafficBootDelay leaves the panel time to settle before the first poll;
// mirrors the ACME worker's boot delay.
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

// trafficPollSeconds is OVM_TRAFFIC_POLL_SECONDS (default 60). A non-positive
// or unparsable value falls back to the default rather than spinning the loop.
func trafficPollSeconds() int {
	if v := strings.TrimSpace(envOrFile("OVM_TRAFFIC_POLL_SECONDS")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return n
		}
	}
	return 60
}

// startTrafficWorker launches the traffic poll loop once per process.
// Idempotent, so Mount can call it unconditionally.
func (h *Handler) startTrafficWorker() {
	trafficWorkerOnce.Do(func() {
		go func() {
			defer func() { recover() }()
			time.Sleep(trafficBootDelay)
			ticker := time.NewTicker(time.Duration(trafficPollSeconds()) * time.Second)
			defer ticker.Stop()
			for range ticker.C {
				runGuarded("traffic worker", h.trafficTick)
			}
		}()
	})
}

// trafficTick runs one accounting pass. SwapDB-safe: h.Svc.DB() is read per
// tick, not cached.
func (h *Handler) trafficTick() {
	db := h.Svc.DB()
	res := runTrafficSync(db)
	log.Printf("traffic: polled %d node(s), failed %d, users updated %d, seeded %d, billed %d bytes",
		res.NodesPolled, res.NodesFailed, res.UsersUpdated, res.UsersSeeded, res.BytesBilled)
	recordAliasCollisions(db, res)
}

// recordAliasCollisions surfaces the (user, node) pairs where a node reported
// more than one key for the same user. The bytes are summed, so nothing is
// lost — but a node whose keying has drifted is worth knowing about, and the
// accounting package cannot write the event itself (internal/telemetry
// imports internal/node, so the reverse would be an import cycle).
func recordAliasCollisions(db *sql.DB, res node.TrafficResult) {
	for _, msg := range res.AmbiguousKeys {
		log.Printf("traffic: ambiguous usage key; accounting deferred: %s", msg)
		telemetry.RecordEvent(db, "traffic_ambiguous_key", "warning",
			"A node usage key matches both a username and another user's ID; accounting for both users on that node was deferred.",
			map[string]any{"target": msg, "detail": msg})
	}
	for _, msg := range res.AliasCollisions {
		log.Printf("traffic: alias keys for one user: %s", msg)
		telemetry.RecordEvent(db, "traffic_alias_keys", "warning",
			"A node reported more than one key for the same user; the byte pools were summed.",
			map[string]any{"target": msg, "detail": msg})
	}
}

// syncTraffic is POST /maintenance/sync-traffic: run one accounting pass now
// and return its TrafficResult envelope.
func (h *Handler) syncTraffic(w http.ResponseWriter, r *http.Request) {
	db := h.Svc.DB()
	res := runTrafficSync(db)
	recordAliasCollisions(db, res)
	envelope(w, true, "Traffic synced", res)
}
