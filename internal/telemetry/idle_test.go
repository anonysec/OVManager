package telemetry

import "testing"

// TestIdleWindow pins the §5.2 cadence gate: a poll is skipped while the
// snapshot is within the current window (PollSeconds with subscribers,
// idlePollSeconds without). now/last are seconds-since-start, so the test is
// deterministic and never sleeps.
func TestIdleWindow(t *testing.T) {
	resetLiveState()
	// The idle default is 300s.
	if got := idlePollSeconds(); got != 300 {
		t.Fatalf("idlePollSeconds default = %v, want 300", got)
	}

	// No subscribers: 300s window.
	snap.mu.Lock()
	snap.lastPoll = 1000
	snap.mu.Unlock()
	if pollDue(1000 + idlePollSeconds() - 1) {
		t.Errorf("tick %vs old = due, want skipped (idle window)", idlePollSeconds()-1)
	}
	if !pollDue(1000 + idlePollSeconds()) {
		t.Errorf("tick %vs old = skipped, want due (idle window)", idlePollSeconds())
	}

	// A browser holds the stream open: PollSeconds window.
	ch := DefaultBus.Subscribe()
	defer DefaultBus.Unsubscribe(ch)
	if got := PollSeconds(); got != 30 {
		t.Fatalf("PollSeconds default = %v, want 30", got)
	}
	snap.mu.Lock()
	snap.lastPoll = 2000
	snap.mu.Unlock()
	if pollDue(2000 + 29) {
		t.Errorf("tick 29s old with subscriber = due, want skipped")
	}
	if !pollDue(2000 + 31) {
		t.Errorf("tick 31s old with subscriber = skipped, want due")
	}

	// Never polled: always due, even with a fresh-looking clock.
	snap.mu.Lock()
	snap.lastPoll = 0
	snap.mu.Unlock()
	if !pollDue(1) {
		t.Errorf("first poll = skipped, want due")
	}
}

// TestPollSecondsEnv pins the OVMANAGER_LIVE_POLL_SECONDS override the worker
// wires into its ticker.
func TestPollSecondsEnv(t *testing.T) {
	t.Setenv("OVMANAGER_LIVE_POLL_SECONDS", "")
	if got := PollSeconds(); got != 30 {
		t.Fatalf("default = %v, want 30", got)
	}
	t.Setenv("OVMANAGER_LIVE_POLL_SECONDS", "45")
	if got := PollSeconds(); got != 45 {
		t.Fatalf("override = %v, want 45", got)
	}
}
