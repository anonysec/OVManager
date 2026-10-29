package panel

import (
	"database/sql"

	"github.com/anonysec/OVManager/go/internal/node"
)

// setLiveCollect swaps the collector and returns a restore func.
func setLiveCollect(fn func(*sql.DB)) (restore func()) {
	liveCollectMu.Lock()
	prev := liveCollect
	liveCollect = fn
	liveCollectMu.Unlock()
	return func() {
		liveCollectMu.Lock()
		liveCollect = prev
		liveCollectMu.Unlock()
	}
}

// setTrafficSync swaps the accounting function and returns a restore func.
func setTrafficSync(fn func(*sql.DB) node.TrafficResult) (restore func()) {
	trafficSyncMu.Lock()
	prev := trafficSync
	trafficSync = fn
	trafficSyncMu.Unlock()
	return func() {
		trafficSyncMu.Lock()
		trafficSync = prev
		trafficSyncMu.Unlock()
	}
}
