package node

import (
	"sync"
	"testing"
	"time"
)

// Swapping the concurrency cap while calls are running must not race with
// them: the swap writes the semaphore the running calls read and release.
func TestFanoutLimitSwapDoesNotRaceWithRunningCalls(t *testing.T) {
	resetForTests()
	defer resetForTests()

	stop := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			RunBounded(func() any { time.Sleep(time.Millisecond); return nil })
		}
	}()

	for i := 0; i < 50; i++ {
		restore := setFanoutLimit(1 + i%3)
		restore()
	}
	close(stop)
	wg.Wait()
}
