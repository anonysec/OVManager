package node

import (
	"testing"
	"time"
)

func TestGatherNodesDeadlineRace(t *testing.T) {
	calls := []func() any{
		func() any {
			time.Sleep(200 * time.Millisecond)
			return 42
		},
	}
	res := GatherNodes(calls, 10*time.Millisecond)
	// Read the returned slice while the straggler goroutine is still running.
	for i := range res {
		_ = res[i]
	}
	time.Sleep(300 * time.Millisecond)
}
