package node

import (
	"fmt"
	"sync"
	"testing"
)

func TestNodeClientHeadersRace(t *testing.T) {
	n := &Node{ID: 1, Name: "n", Address: "127.0.0.1", Port: 1, Key: "k"}
	_ = NodeClient(n, "panel-a")
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			c := NodeClient(n, fmt.Sprintf("panel-%d", i))
			if c == nil {
				return
			}
			_ = c.panelIDHeader()
		}(i)
	}
	wg.Wait()
}

func TestPanelIDHeaderResolution(t *testing.T) {
	resetForTests()
	defer resetForTests()

	// Uncached client (NodeID == 0) carries its own panel id.
	c0, err := NewClient("127.0.0.1", 1, "k", "", "panel-u", 0)
	if err != nil {
		t.Fatal(err)
	}
	if got := c0.panelIDHeader(); got != "panel-u" {
		t.Errorf("uncached panelIDHeader = %q, want panel-u", got)
	}
	// Cached client resolves it from the registry.
	n := &Node{ID: 7, Name: "n", Address: "127.0.0.1", Port: 1, Key: "k"}
	cached := NodeClient(n, "panel-c")
	if cached == nil {
		t.Fatal("NodeClient returned nil")
	}
	if got := cached.panelIDHeader(); got != "panel-c" {
		t.Errorf("cached panelIDHeader = %q, want panel-c", got)
	}
}
