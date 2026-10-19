package panel

import (
	"sync"
	"testing"
)

// TestRecordCheckTransitionRace drives the package-level checkState map from
// many goroutines at once (two concurrent /overview requests). Run with -race:
// the unsynchronised map is a fatal-class concurrent write.
func TestRecordCheckTransitionRace(t *testing.T) {
	h := &Handler{}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			h.recordCheckTransition(check{ID: "race-test", Status: "ok", Summary: "s"})
		}()
	}
	wg.Wait()
}
