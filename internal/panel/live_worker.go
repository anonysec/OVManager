// Live snapshot worker (design §5.1): the single goroutine that drives
// telemetry.CollectLiveSnapshot on a ticker at telemetry.PollSeconds(). It is
// the only caller, so the collector's lock-free grace/alert state stays
// single-writer. The idle cadence itself lives in the collector's pollDue gate.
package panel

import (
	"database/sql"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// liveBootDelay leaves the panel time to settle before the first poll; mirrors
// the ACME worker's boot delay.
const liveBootDelay = 15 * time.Second

var liveWorkerOnce sync.Once

// liveCollect is telemetry.CollectLiveSnapshot behind a mutex-guarded seam so
// the worker test can count ticks without a live node (and stay race-clean).
var (
	liveCollectMu sync.Mutex
	liveCollect   = telemetry.CollectLiveSnapshot
)

func runLiveCollect(db *sql.DB) {
	liveCollectMu.Lock()
	fn := liveCollect
	liveCollectMu.Unlock()
	fn(db)
}

// startLiveWorker launches the live snapshot loop once per process.
// Idempotent, so Mount can call it unconditionally.
func (h *Handler) startLiveWorker() {
	liveWorkerOnce.Do(func() {
		go func() {
			defer func() { recover() }()
			time.Sleep(liveBootDelay)
			ticker := time.NewTicker(livePollInterval())
			defer ticker.Stop()
			for range ticker.C {
				runGuarded("live worker", h.liveTick)
			}
		}()
	})
}

// livePollInterval clamps PollSeconds to a positive interval: a 0/negative env
// value would panic time.NewTicker.
func livePollInterval() time.Duration {
	secs := telemetry.PollSeconds()
	if secs <= 0 {
		secs = 30
	}
	return time.Duration(secs * float64(time.Second))
}

// liveTick runs one collector pass. SwapDB-safe: h.Svc.DB() is read per tick.
func (h *Handler) liveTick() {
	db := h.Svc.DB()
	runLiveCollect(db)
	telemetry.CollectMetricsIfDue(db)
}
