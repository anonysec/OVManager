// Package telemetry ports backend/routers/telemetry.py plus the observability
// modules it stands on (audit, live, metrics, thresholds, notifier,
// node_alerts).
//
// Two halves:
//   - stream.go: the in-process event bus, the live snapshot, the SSE handler
//     and the background collector (backend/operations/observability/live.py).
//   - handler.go: activity, notifications and metrics endpoints plus the
//     audit / threshold / notifier helpers they and the collector use.
package telemetry

import (
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf16"

	"ovmanager-go/internal/auth"
)

// --- event bus (live.py LiveBus) ---

// KV is one ordered object member. Python dicts preserve insertion order and
// json.dumps serialises in that order, so the SSE wire format carries order
// explicitly instead of a Go map (which marshals sorted).
type KV struct {
	Key string
	Val any
}

// Event is one published invalidation (live.py LiveEvent).
type Event struct {
	Topic string
	Data  []KV
	TS    float64
}

// Bus fans one event out to every subscriber (live.py LiveBus).
type Bus struct {
	mu   sync.Mutex
	subs map[chan Event]struct{}
}

// NewBus builds an empty bus.
func NewBus() *Bus { return &Bus{subs: map[chan Event]struct{}{}} }

// Subscribe registers a subscriber with a 100-deep queue like the Python bus.
func (b *Bus) Subscribe() chan Event {
	ch := make(chan Event, 100)
	b.mu.Lock()
	b.subs[ch] = struct{}{}
	b.mu.Unlock()
	return ch
}

// Unsubscribe drops a subscriber.
func (b *Bus) Unsubscribe(ch chan Event) {
	b.mu.Lock()
	delete(b.subs, ch)
	b.mu.Unlock()
}

// HasSubscribers reports whether anyone is watching (collector idle gate).
func (b *Bus) HasSubscribers() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.subs) > 0
}

// Publish delivers event to every subscriber. Non-blocking: a full queue drops
// its oldest entry, mirroring asyncio.QueueFull handling.
func (b *Bus) Publish(topic string, data ...KV) {
	ev := Event{Topic: topic, Data: data, TS: nowSecs()}
	b.mu.Lock()
	subs := make([]chan Event, 0, len(b.subs))
	for ch := range b.subs {
		subs = append(subs, ch)
	}
	b.mu.Unlock()
	for _, ch := range subs {
		select {
		case ch <- ev:
		default:
			select {
			case <-ch: // drop oldest
			default:
			}
			select {
			case ch <- ev:
			default:
			}
		}
	}
}

// --- live snapshot (live.py LiveSnapshot) ---

// SnapshotMaxNodes is the default cap on tracked nodes.
const SnapshotMaxNodes = 50

// SnapshotMaxNodesKey is the settings_kv key overriding the cap.
const SnapshotMaxNodesKey = "telemetry.snapshot_max_nodes"

var procStart = time.Now()

type snapshotState struct {
	mu          sync.Mutex
	connections map[string]int
	nodes       map[string]bool
	lastPoll    float64 // seconds since procStart; 0 = never
	capacity    int
}

var snap = &snapshotState{connections: map[string]int{}, nodes: map[string]bool{}, capacity: SnapshotMaxNodes}

// SnapshotCap returns the configured node cap.
func SnapshotCap() int {
	snap.mu.Lock()
	defer snap.mu.Unlock()
	return snap.capacity
}

// Connections returns a copy of the per-user live connection counts.
func Connections() map[string]int {
	snap.mu.Lock()
	defer snap.mu.Unlock()
	out := make(map[string]int, len(snap.connections))
	for k, v := range snap.connections {
		out[k] = v
	}
	return out
}

// NodeOnline returns a copy of the per-node reachability snapshot.
func NodeOnline() map[string]bool {
	snap.mu.Lock()
	defer snap.mu.Unlock()
	out := make(map[string]bool, len(snap.nodes))
	for k, v := range snap.nodes {
		out[k] = v
	}
	return out
}

// SnapshotFresh reports whether the collector polled within the idle window.
func SnapshotFresh() bool {
	snap.mu.Lock()
	ts := snap.lastPoll
	snap.mu.Unlock()
	return ts != 0 && time.Since(procStart).Seconds()-ts <= idlePollSeconds()
}

// updateSnapshot stores a new snapshot; returns (connectionsChanged, nodesChanged).
func updateSnapshot(connections map[string]int, nodes map[string]bool, cap int) (bool, bool) {
	if cap > 0 && len(nodes) > cap {
		names := make([]string, 0, len(nodes))
		for name := range nodes {
			names = append(names, name)
		}
		sortStrings(names)
		trimmed := map[string]bool{}
		for _, name := range names[:cap] {
			trimmed[name] = nodes[name]
		}
		nodes = trimmed
	}
	snap.mu.Lock()
	defer snap.mu.Unlock()
	countsChanged := !sameInts(connections, snap.connections)
	nodesChanged := !sameBools(nodes, snap.nodes)
	snap.connections = connections
	snap.nodes = nodes
	if cap == 0 {
		cap = SnapshotMaxNodes
	}
	snap.capacity = cap
	snap.lastPoll = time.Since(procStart).Seconds()
	return countsChanged, nodesChanged
}

// --- SSE handler (routers/telemetry.py live_stream) ---

// heartbeatSeconds mirrors _HEARTBEAT_SECONDS.
const heartbeatSeconds = 15

// StreamHandler returns the SSE endpoint bound to bus b.
func StreamHandler(svc *auth.Service, b *Bus) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := svc.CurrentUser(r); !ok {
			w.Header().Set("WWW-Authenticate", "Bearer")
			auth.WriteDetail(w, http.StatusUnauthorized, "Could not validate credentials")
			return
		}
		flusher, ok := w.(http.Flusher)
		if !ok {
			auth.WriteDetail(w, http.StatusInternalServerError, "streaming unsupported")
			return
		}
		h := w.Header()
		h.Set("Content-Type", "text/event-stream")
		h.Set("Cache-Control", "no-cache")
		h.Set("X-Accel-Buffering", "no")
		w.WriteHeader(http.StatusOK)

		q := b.Subscribe()
		defer b.Unsubscribe(q)
		// ready frame: {"ts": <time>, "cap": <cap>} — ts first, like the dict.
		_, _ = w.Write([]byte("event: ready\ndata: " + pyObject([]KV{{"ts", nowSecs()}, {"cap", SnapshotCap()}}) + "\n\n"))
		flusher.Flush()

		timer := time.NewTimer(heartbeatSeconds * time.Second)
		defer timer.Stop()
		for {
			select {
			case <-r.Context().Done():
				return
			case ev := <-q:
				_, _ = w.Write([]byte(formatEvent(ev.Topic, ev.TS, ev.Data)))
				flusher.Flush()
			case <-timer.C:
				_, _ = w.Write([]byte(": hb\n\n"))
				flusher.Flush()
				timer.Reset(heartbeatSeconds * time.Second)
			}
		}
	}
}

// formatEvent renders one SSE frame: `event: <topic>\ndata: <json>\n\n`.
func formatEvent(topic string, ts float64, data []KV) string {
	pairs := make([]KV, 0, len(data)+1)
	pairs = append(pairs, data...)
	pairs = append(pairs, KV{"ts", ts})
	return "event: " + topic + "\ndata: " + pyObject(pairs) + "\n\n"
}

// --- Python-compatible JSON for the SSE body (json.dumps default=str) ---

// pyObject renders an ordered object with Python's default separators.
func pyObject(pairs []KV) string {
	var sb strings.Builder
	sb.WriteByte('{')
	for i, p := range pairs {
		if i > 0 {
			sb.WriteString(", ")
		}
		sb.WriteString(pyString(p.Key))
		sb.WriteString(": ")
		sb.WriteString(pyValue(p.Val))
	}
	sb.WriteByte('}')
	return sb.String()
}

func pyValue(v any) string {
	switch x := v.(type) {
	case nil:
		return "null"
	case bool:
		if x {
			return "true"
		}
		return "false"
	case string:
		return pyString(x)
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return pyFloat(x)
	case []KV:
		return pyObject(x)
	case []any:
		parts := make([]string, len(x))
		for i, item := range x {
			parts[i] = pyValue(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	default:
		return pyString(strings.TrimSpace(pyFallback(x)))
	}
}

func pyFallback(v any) string {
	if s, ok := v.(interface{ String() string }); ok {
		return s.String()
	}
	return ""
}

// pyFloat matches Python's repr for the magnitudes a unix ts takes.
//
// ponytail: fixed shortest form; Python switches to exponent form below 1e-4
// or at/above 1e16. SSE floats are unix seconds, so that range never occurs.
func pyFloat(f float64) string {
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.ContainsRune(s, '.') {
		s += ".0" // Python prints 100.0, not 100
	}
	return s
}

// pyString mirrors json.dumps ensure_ascii escaping.
func pyString(s string) string {
	var sb strings.Builder
	sb.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			sb.WriteString(`\"`)
		case '\\':
			sb.WriteString(`\\`)
		case '\n':
			sb.WriteString(`\n`)
		case '\r':
			sb.WriteString(`\r`)
		case '\t':
			sb.WriteString(`\t`)
		default:
			switch {
			case r < 0x20:
				sb.WriteString(unicodeEscape(uint16(r)))
			case r < 0x7f:
				sb.WriteRune(r)
			case r <= 0xffff:
				sb.WriteString(unicodeEscape(uint16(r)))
			default:
				hi, lo := utf16.EncodeRune(r)
				sb.WriteString(unicodeEscape(uint16(hi)))
				sb.WriteString(unicodeEscape(uint16(lo)))
			}
		}
	}
	sb.WriteByte('"')
	return sb.String()
}

func unicodeEscape(u uint16) string {
	const hex = "0123456789abcdef"
	buf := []byte{'\\', 'u', 0, 0, 0, 0}
	buf[2] = hex[(u>>12)&0xf]
	buf[3] = hex[(u>>8)&0xf]
	buf[4] = hex[(u>>4)&0xf]
	buf[5] = hex[u&0xf]
	return string(buf)
}

// --- small shared helpers ---

func nowSecs() float64 { return float64(time.Now().UnixNano()) / 1e9 }

func sortStrings(s []string) {
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}

func sameInts(a, b map[string]int) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}

func sameBools(a, b map[string]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for k, v := range a {
		if b[k] != v {
			return false
		}
	}
	return true
}
