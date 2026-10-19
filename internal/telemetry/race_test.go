package telemetry

import (
	"sync"
	"testing"
)

// TestCheckNodeAlertsRace drives the package-level node-alert maps from many
// goroutines at once (two concurrent POST /metrics/collect calls). Run with
// -race: the unsynchronised maps are a fatal-class concurrent write.
func TestCheckNodeAlertsRace(t *testing.T) {
	rows := []map[string]any{
		{"node_id": int64(1), "node_name": "n1", "reachable": 1},
		{"node_id": int64(2), "node_name": "n2", "reachable": 1},
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			checkNodeAlerts(nil, rows, false)
		}()
	}
	wg.Wait()
}

// TestApplyGraceRace drives graceUntil from several goroutines, mirroring a
// manual collect racing the live worker tick.
func TestApplyGraceRace(t *testing.T) {
	prev := map[string]bool{"a": true, "b": true}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			applyGrace(map[string]bool{}, prev, 100)
		}()
	}
	wg.Wait()
}
