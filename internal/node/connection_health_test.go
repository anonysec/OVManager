package node

import (
	"testing"
	"time"
)

// Healthy decides the probe timeout: a node we have not heard from recently
// gets the SHORT timeout, so a black-holed node cannot hold a fan-out slot
// for the long one.
func TestHealthyFollowsTheNodeState(t *testing.T) {
	resetForTests()
	defer resetForTests()

	// A node we have never contacted is optimistic: it may simply be slow to
	// start, so it gets the long probe timeout.
	if !Healthy(&Node{ID: 99}) {
		t.Error("a node with no connection entry should be treated as healthy")
	}

	// A node that answered recently is healthy.
	connMu.Lock()
	connections[1] = &connection{client: &Client{}, health: HealthHealthy, lastOK: time.Now()}
	connMu.Unlock()
	if !Healthy(&Node{ID: 1}) {
		t.Error("a node that just answered should be healthy")
	}

	// A node that has gone quiet is not: it gets the short probe timeout.
	connMu.Lock()
	connections[1].lastOK = time.Now().Add(-2 * healthTTL)
	connMu.Unlock()
	if Healthy(&Node{ID: 1}) {
		t.Error("a node that has not answered for over the TTL should not be healthy")
	}

	// A node we have never had an answer from is not healthy either.
	connMu.Lock()
	connections[2] = &connection{client: &Client{}, health: HealthUnknown}
	connMu.Unlock()
	if Healthy(&Node{ID: 2}) {
		t.Error("a node that never answered should not be healthy")
	}

	// A known-broken node is not.
	connMu.Lock()
	connections[3] = &connection{client: &Client{}, health: HealthBroken}
	connMu.Unlock()
	if Healthy(&Node{ID: 3}) {
		t.Error("a broken node should not be healthy")
	}
}

// The probe timeout follows the health: a node that is not healthy must be
// probed briefly, or it holds a fan-out slot for the long timeout.
func TestProbeTimeoutFollowsHealth(t *testing.T) {
	resetForTests()
	defer resetForTests()

	connMu.Lock()
	connections[1] = &connection{client: &Client{}, health: HealthHealthy, lastOK: time.Now().Add(-2 * healthTTL)}
	connMu.Unlock()

	if got := ProbeTimeout(&Node{ID: 1}); got != BrokenProbeTimeout {
		t.Errorf("ProbeTimeout = %v, want %v for a node that has gone quiet", got, BrokenProbeTimeout)
	}
}
