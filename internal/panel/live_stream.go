// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Event stream supervisor: one GET /sync/events consumer per active node.
// While any node is supervised, the live snapshot collector stands down
// (telemetry.StreamsActive) so snapshot state has a single writer; nodes that
// predate the endpoint answer 404/405 once and keep their polling path.
package panel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"math/rand/v2"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/node"
	"github.com/anonysec/OVManager/internal/telemetry"
)

// Cadences. Vars, not consts, so the supervisor tests can run them fast
// without sleeping for the production intervals.
var (
	// streamReconcileEvery re-reads the node table so added, removed and
	// deactivated nodes pick up or drop their stream without a restart.
	streamReconcileEvery = 30 * time.Second
	// streamJitter spreads first dials after a panel restart.
	streamJitter = 2 * time.Second
	// streamBackoffBase is the first retry wait after a failed dial; it
	// doubles per consecutive failure up to streamBackoffMax.
	streamBackoffBase = time.Second
	streamBackoffMax  = 60 * time.Second
	// streamFallbackProbe re-probes a node that answered ErrNoEvents. Keeping
	// the fallback permanent would need a panel restart before an upgraded
	// node could stream; one request per node per few minutes is not a hot
	// loop and lets the node upgrade take effect on its own.
	streamFallbackProbe = 5 * time.Minute
)

// streamOfflineAfter is the consecutive failed dials that mark a node
// offline through the collector's grace path. One failure is a blip; two is a
// stream that is not coming back on its own.
const streamOfflineAfter = 2

// streamHooks is the telemetry seam: production wires the real functions;
// the supervisor tests swap them to observe what reached telemetry without
// depending on process-wide snapshot state.
type streamHooks struct {
	apply     func(db *sql.DB, n *node.Node, sess *node.SessionsResponse, usageTotals map[string]uint64) error
	offline   func(nodeName string)
	setActive func(on bool)
}

var (
	streamHooksMu  sync.Mutex
	streamHooksNow = streamHooks{
		apply:     telemetry.ApplyNodeSessions,
		offline:   telemetry.MarkNodeOffline,
		setActive: telemetry.SetStreamsActive,
	}
)

func currentStreamHooks() streamHooks {
	streamHooksMu.Lock()
	defer streamHooksMu.Unlock()
	return streamHooksNow
}

// streamSupervisor owns the per-node loops. loops holds a cancel func per
// supervised node id — its presence is also the "feed is owned by streams"
// signal — and fallback records nodes that answered ErrNoEvents.
type streamSupervisor struct {
	mu    sync.Mutex
	loops map[int64]context.CancelFunc
	names map[int64]string
	// fallback holds the next probe time for nodes that answered ErrNoEvents;
	// notified remembers which fallbacks were already logged so the line
	// appears once per node, not once per probe.
	fallback map[int64]time.Time
	notified map[int64]bool
}

func newStreamSupervisor() *streamSupervisor {
	return &streamSupervisor{
		loops:    map[int64]context.CancelFunc{},
		names:    map[int64]string{},
		fallback: map[int64]time.Time{},
		notified: map[int64]bool{},
	}
}

// startEventStreams launches the reconcile loop once per process.
func (h *Handler) startEventStreams() {
	streamsOnce.Do(func() {
		sup := newStreamSupervisor()
		Run(context.Background(), []job{{
			name:  "live streams",
			delay: liveBootDelay,
			every: func() time.Duration { return streamReconcileEvery },
			fn:    func(ctx context.Context) { sup.reconcile(ctx, h.Svc.DB()) },
		}})
	})
}

var streamsOnce sync.Once

// reconcile starts a loop for every active node that has none and stops the
// loops of nodes that are no longer active.
func (s *streamSupervisor) reconcile(ctx context.Context, db *sql.DB) {
	hooks := currentStreamHooks()
	nodes := node.GetActiveNodes(db)
	seen := map[int64]bool{}
	start := make([]int64, 0, len(nodes))
	now := time.Now()
	s.mu.Lock()
	for _, n := range nodes {
		seen[n.ID] = true
		s.names[n.ID] = n.Name
		if _, running := s.loops[n.ID]; running {
			continue
		}
		// A fallback node is re-probed only once its window has passed.
		if next, fellBack := s.fallback[n.ID]; fellBack && now.Before(next) {
			continue
		}
		start = append(start, n.ID)
	}
	stale := map[int64]string{}
	for id, cancel := range s.loops {
		if !seen[id] {
			cancel()
			delete(s.loops, id)
		}
	}
	for id, name := range s.names {
		if !seen[id] {
			stale[id] = name
			delete(s.names, id)
			delete(s.fallback, id)
			delete(s.notified, id)
		}
	}
	for _, id := range start {
		loopCtx, cancel := context.WithCancel(ctx)
		s.loops[id] = cancel
		go s.runNode(loopCtx, db, id)
	}
	s.mu.Unlock()
	// A node that stopped being active loses its snapshot contribution; the
	// collector's grace path governs the badge, exactly as for a failed poll.
	for _, name := range stale {
		hooks.offline(name)
	}
	s.refreshActive()
}

// runNode keeps one node's stream open: dial, apply frames, back off.
func (s *streamSupervisor) runNode(ctx context.Context, db *sql.DB, nodeID int64) {
	hooks := currentStreamHooks()
	// Spread the first dials; a panel restart must not open the whole fleet
	// in the same instant.
	if !sleepCtx(ctx, jitter(streamJitter)) {
		s.drop(nodeID)
		return
	}
	backoff := streamBackoffBase
	failures := 0
	for {
		if ctx.Err() != nil {
			s.drop(nodeID)
			return
		}
		n := node.GetNodeByID(db, nodeID)
		if n == nil {
			s.drop(nodeID)
			return
		}
		s.mu.Lock()
		s.names[nodeID] = n.Name
		s.mu.Unlock()

		// lastRev resets per connection: a fresh stream's snapshot (revision
		// 0) is trusted unconditionally, so frames lost across a reconnect
		// can never stick (Review Focus 2).
		connected := false
		lastRev := int64(-1)
		err := node.NodeClient(n, node.PanelIDFor(db)).StreamEvents(ctx, func(ev node.NodeEvent) error {
			if ev.Revision <= lastRev {
				return nil // stale frame on this connection
			}
			lastRev = ev.Revision
			connected = true
			switch ev.Kind {
			case "snapshot", "sessions":
				var sess node.SessionsResponse
				if err := json.Unmarshal(ev.Data, &sess); err != nil {
					return nil
				}
				return hooks.apply(db, n, &sess, nil)
			case "usage":
				// Display-only sample: billing stays on the traffic pass.
				var body struct {
					Totals map[string]uint64 `json:"totals"`
				}
				if err := json.Unmarshal(ev.Data, &body); err != nil {
					return nil
				}
				return hooks.apply(db, n, nil, body.Totals)
			}
			return nil
		})
		if errors.Is(err, node.ErrNoEvents) {
			s.mu.Lock()
			s.fallback[nodeID] = time.Now().Add(streamFallbackProbe)
			fresh := !s.notified[nodeID]
			s.notified[nodeID] = true
			delete(s.loops, nodeID)
			s.mu.Unlock()
			if fresh {
				log.Printf("live: node %s predates event streaming; polling instead", n.Name)
			}
			s.refreshActive()
			return
		}
		if ctx.Err() != nil {
			s.drop(nodeID)
			return
		}
		if connected {
			// A stream that delivered frames was healthy: the node supports
			// the endpoint, so a later fallback may log again.
			s.mu.Lock()
			delete(s.notified, nodeID)
			delete(s.fallback, nodeID)
			s.mu.Unlock()
			failures = 0
			backoff = streamBackoffBase
		} else {
			failures++
			if failures >= streamOfflineAfter {
				// Re-applied on every retry past the threshold so the grace
				// window can actually expire: one call would hold the badge
				// green forever while the node stays down.
				hooks.offline(n.Name)
			}
		}
		// Jitter is additive (never shortens the floor), and the cap keeps a
		// dead node from becoming a hot loop.
		wait := backoff + jitter(backoff/4+1)
		if !sleepCtx(ctx, wait) {
			s.drop(nodeID)
			return
		}
		backoff *= 2
		if backoff > streamBackoffMax {
			backoff = streamBackoffMax
		}
	}
}

// drop unsupervises a node and re-evaluates the single-writer gate.
func (s *streamSupervisor) drop(nodeID int64) {
	s.mu.Lock()
	delete(s.loops, nodeID)
	s.mu.Unlock()
	s.refreshActive()
}

// refreshActive publishes the single-writer gate: streams own snapshot state
// while at least one active node is supervised.
func (s *streamSupervisor) refreshActive() {
	s.mu.Lock()
	active := len(s.loops) > 0
	s.mu.Unlock()
	currentStreamHooks().setActive(active)
}

// jitter returns a random duration in [0, d); zero for a non-positive d.
func jitter(d time.Duration) time.Duration {
	if d <= 0 {
		return 0
	}
	return rand.N(d) // #nosec G404 -- timer jitter, not a secret
}

// sleepCtx waits d, returning false when ctx is done first.
func sleepCtx(ctx context.Context, d time.Duration) bool {
	if d <= 0 {
		return ctx.Err() == nil
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return true
	case <-ctx.Done():
		return false
	}
}
