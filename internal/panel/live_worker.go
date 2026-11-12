// Live snapshot worker: the single goroutine that drives
// telemetry.CollectLiveSnapshot on a ticker at telemetry.PollSeconds(). It is
// the only caller, so the collector's lock-free grace/alert state stays
// single-writer. The idle cadence itself lives in the collector's pollDue gate.
package panel

import (
	"context"
	"database/sql"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/telemetry"
)

// liveBootDelay leaves the panel time to settle before the first poll.
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
func (h *Handler) startLiveWorker() {
	liveWorkerOnce.Do(func() {
		Run(context.Background(), []job{{
			name:  "live worker",
			delay: liveBootDelay,
			every: livePollInterval,
			fn:    func(ctx context.Context) { h.liveTick(ctx) },
		}})
	})
}

// livePollInterval clamps PollSeconds to a positive interval.
func livePollInterval() time.Duration {
	secs := telemetry.PollSeconds()
	if secs <= 0 {
		secs = 30
	}
	return time.Duration(secs * float64(time.Second))
}

// liveTick runs one collector pass. SwapDB-safe: h.Svc.DB() is read per tick.
func (h *Handler) liveTick(ctx context.Context) {
	select {
	case <-ctx.Done():
		return
	default:
	}
	db := h.Svc.DB()
	// While an event stream owns snapshot state the poll collector stands
	// down, so the ticker and the stream consumer are never both writers
	// (Review Focus 5). Metrics history and alerts keep their own cadence:
	// they read sessions but never write snapshot state or billing totals.
	if !telemetry.StreamsActive() {
		runLiveCollect(db)
	}
	telemetry.CollectMetricsIfDue(db)
}
