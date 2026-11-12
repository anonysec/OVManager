// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"context"
	"database/sql"
	"encoding/pem"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
	"github.com/anonysec/OVManager/internal/node"
	"github.com/anonysec/OVManager/internal/telemetry"
)

// streamSchema is the slice of the panel schema the supervisor reads: the
// node row as node.GetNodeByID scans it, plus the Setting/User tables the
// live tick touches.
const streamSchema = `
CREATE TABLE Admin (id INTEGER PRIMARY KEY, username VARCHAR UNIQUE, password VARCHAR,
  is_owner BOOLEAN DEFAULT 0, telegram_id INTEGER);
CREATE TABLE User (id INTEGER PRIMARY KEY, uuid VARCHAR, name VARCHAR UNIQUE, total BIGINT,
  used BIGINT, last_node_usage BIGINT DEFAULT 0, node_usage VARCHAR DEFAULT '{}',
  max_logins INTEGER DEFAULT 1, is_active BOOLEAN DEFAULT 1, last_online VARCHAR);
CREATE TABLE Node (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR,
  tunnel_address VARCHAR DEFAULT '', protocol VARCHAR DEFAULT 'tcp',
  ovpn_port INTEGER DEFAULT 1194, port INTEGER DEFAULT 2083, key VARCHAR DEFAULT '',
  status BOOLEAN DEFAULT 1, server_ca VARCHAR, country_code VARCHAR, latitude REAL,
  longitude REAL, extra_ports VARCHAR DEFAULT '', settings TEXT DEFAULT '{}');
CREATE TABLE Setting (id INTEGER PRIMARY KEY, panel_id VARCHAR, bot_enabled BOOLEAN DEFAULT 0);
`

func newStreamDB(t *testing.T) (*sql.DB, string) {
	t.Helper()
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "stream.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(streamSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn, dir
}

// addStreamNode inserts an active node pinned to srv's certificate.
func addStreamNode(t *testing.T, conn *sql.DB, id int64, name string, srv *httptest.Server) {
	t.Helper()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(u.Port())
	pin := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
	if _, err := conn.Exec(
		`INSERT INTO Node (id, name, address, port, status, server_ca) VALUES (?, ?, ?, ?, 1, ?)`,
		id, name, u.Hostname(), port, pin,
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}
	t.Cleanup(func() { node.Forget(id) })
}

// withStreamHooks swaps the telemetry seam for the test and restores it.
func withStreamHooks(t *testing.T, hooks streamHooks) {
	t.Helper()
	streamHooksMu.Lock()
	prev := streamHooksNow
	streamHooksNow = hooks
	streamHooksMu.Unlock()
	t.Cleanup(func() {
		streamHooksMu.Lock()
		streamHooksNow = prev
		streamHooksMu.Unlock()
	})
}

func withoutJitter(t *testing.T) {
	t.Helper()
	prev := streamJitter
	streamJitter = 0
	t.Cleanup(func() { streamJitter = prev })
}

// waitStreamIdle blocks until every node loop has exited.
func waitStreamIdle(t *testing.T, sup *streamSupervisor) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		sup.mu.Lock()
		running := len(sup.loops)
		sup.mu.Unlock()
		if running == 0 {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("supervisor loops did not stop")
}

// sseStream is a fake node /sync/events endpoint: the handler writes frames
// once, then holds the stream open until the panel hangs up.
func sseStream(t *testing.T, frames string) *httptest.Server {
	t.Helper()
	var once sync.Once
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/sync/events" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		fl := w.(http.Flusher)
		w.WriteHeader(http.StatusOK)
		once.Do(func() {
			_, _ = fmt.Fprint(w, frames)
			fl.Flush()
		})
		<-r.Context().Done()
	}))
	t.Cleanup(func() { srv.CloseClientConnections(); srv.Close() })
	return srv
}

func TestSupervisorConnectsAndAppliesSnapshot(t *testing.T) {
	withoutJitter(t)
	conn, _ := newStreamDB(t)
	srv := sseStream(t, "event: snapshot\ndata: {\"revision\":0,\"data\":{\"live_sessions\":[{\"common_name\":\"amy\"}],\"live_count\":1}}\n\n")
	addStreamNode(t, conn, 1, "n1", srv)

	var mu sync.Mutex
	var applied []*node.SessionsResponse
	active := false
	withStreamHooks(t, streamHooks{
		apply: func(_ *sql.DB, _ *node.Node, sess *node.SessionsResponse, _ map[string]uint64) error {
			mu.Lock()
			applied = append(applied, sess)
			mu.Unlock()
			return nil
		},
		offline: func(string) {},
		setActive: func(on bool) {
			mu.Lock()
			active = on
			mu.Unlock()
		},
	})

	sup := newStreamSupervisor()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sup.reconcile(ctx, conn)

	deadline := time.After(3 * time.Second)
	for {
		mu.Lock()
		ok := len(applied) > 0 && len(applied[0].LiveSessions) == 1 &&
			applied[0].LiveSessions[0].CommonName == "amy" && active
		mu.Unlock()
		if ok {
			break
		}
		select {
		case <-deadline:
			t.Fatal("the snapshot frame was not applied")
		case <-time.After(5 * time.Millisecond):
		}
	}
	cancel()
	waitStreamIdle(t, sup)
}

func TestSupervisorBackoffJitter(t *testing.T) {
	withoutJitter(t)
	prevBase := streamBackoffBase
	streamBackoffBase = time.Second
	t.Cleanup(func() { streamBackoffBase = prevBase })

	conn, _ := newStreamDB(t)
	var mu sync.Mutex
	var stamps []time.Time
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		stamps = append(stamps, time.Now())
		mu.Unlock()
		w.WriteHeader(http.StatusInternalServerError)
	}))
	t.Cleanup(func() { srv.CloseClientConnections(); srv.Close() })
	addStreamNode(t, conn, 1, "n1", srv)

	var offlineCalls atomic.Int32
	withStreamHooks(t, streamHooks{
		apply:     func(*sql.DB, *node.Node, *node.SessionsResponse, map[string]uint64) error { return nil },
		offline:   func(string) { offlineCalls.Add(1) },
		setActive: func(bool) {},
	})

	sup := newStreamSupervisor()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sup.reconcile(ctx, conn)

	deadline := time.Now().Add(5 * time.Second)
	for {
		mu.Lock()
		n := len(stamps)
		mu.Unlock()
		if n >= 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the supervisor did not retry")
		}
		time.Sleep(5 * time.Millisecond)
	}
	mu.Lock()
	gap := stamps[1].Sub(stamps[0])
	mu.Unlock()
	if gap < 900*time.Millisecond {
		t.Fatalf("retry after %s, want no faster than the 1 s base backoff", gap)
	}

	// Two consecutive failures is the offline threshold.
	deadline = time.Now().Add(time.Second)
	for offlineCalls.Load() == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if offlineCalls.Load() == 0 {
		t.Fatal("two failed dials did not mark the node offline")
	}
	cancel()
	waitStreamIdle(t, sup)
}

func TestNoEventsNodeFallsBackToPoll(t *testing.T) {
	withoutJitter(t)
	conn, dir := newStreamDB(t)
	var hits atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusNotFound)
	}))
	t.Cleanup(func() { srv.CloseClientConnections(); srv.Close() })
	addStreamNode(t, conn, 1, "n1", srv)

	var mu sync.Mutex
	lastActive := true
	withStreamHooks(t, streamHooks{
		apply: func(*sql.DB, *node.Node, *node.SessionsResponse, map[string]uint64) error {
			t.Error("a 404 node must never reach the apply path")
			return nil
		},
		offline: func(string) {},
		setActive: func(on bool) {
			mu.Lock()
			lastActive = on
			mu.Unlock()
		},
	})

	sup := newStreamSupervisor()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sup.reconcile(ctx, conn)

	deadline := time.Now().Add(3 * time.Second)
	for {
		sup.mu.Lock()
		_, fellBack := sup.fallback[1]
		sup.mu.Unlock()
		if fellBack {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the supervisor did not record the poll fallback")
		}
		time.Sleep(5 * time.Millisecond)
	}
	if got := hits.Load(); got != 1 {
		t.Fatalf("404 node dialed %d times, want exactly one probe", got)
	}
	mu.Lock()
	active := lastActive
	mu.Unlock()
	if active {
		t.Fatal("StreamsActive stayed true for a node without the endpoint")
	}

	// A follow-up reconcile inside the probe window must not re-dial.
	sup.reconcile(ctx, conn)
	time.Sleep(100 * time.Millisecond)
	if got := hits.Load(); got != 1 {
		t.Fatalf("fallback node re-dialed inside the probe window: %d probes", got)
	}

	// After the window it is probed exactly once, so a node upgraded in the
	// meantime starts streaming without a panel restart.
	prevProbe := streamFallbackProbe
	streamFallbackProbe = 50 * time.Millisecond
	t.Cleanup(func() { streamFallbackProbe = prevProbe })
	sup.mu.Lock()
	sup.fallback[1] = time.Now().Add(-time.Millisecond)
	sup.mu.Unlock()
	sup.reconcile(ctx, conn)
	deadline = time.Now().Add(2 * time.Second)
	for hits.Load() < 2 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if got := hits.Load(); got != 2 {
		t.Fatalf("fallback node probed %d times after the window, want 2", got)
	}
	sup.reconcile(ctx, conn)
	time.Sleep(50 * time.Millisecond)
	if got := hits.Load(); got != 2 {
		t.Fatalf("fallback re-probe looped: %d probes", got)
	}

	// The live ticker keeps running for polling nodes.
	h := NewHandler(auth.NewService(conn, dir))
	var ticks atomic.Int32
	restore := setLiveCollect(func(*sql.DB) { ticks.Add(1) })
	defer restore()
	h.liveTick(context.Background())
	if got := ticks.Load(); got != 1 {
		t.Fatalf("live poll skipped for a fallback node: %d ticks, want 1", got)
	}
}

func TestConsumerDropsStaleRevision(t *testing.T) {
	withoutJitter(t)
	conn, _ := newStreamDB(t)
	srv := sseStream(t,
		"event: snapshot\ndata: {\"revision\":0,\"data\":{\"live_sessions\":[{\"common_name\":\"amy\"}]}}\n\n"+
			"event: sessions\ndata: {\"revision\":2,\"data\":{\"live_sessions\":[{\"common_name\":\"bob\"}]}}\n\n"+
			// A frame older than the one already applied: dropped, never applied.
			"event: sessions\ndata: {\"revision\":1,\"data\":{\"live_sessions\":[{\"common_name\":\"carl\"}]}}\n\n")
	addStreamNode(t, conn, 1, "n1", srv)

	var mu sync.Mutex
	var names []string
	withStreamHooks(t, streamHooks{
		apply: func(_ *sql.DB, _ *node.Node, sess *node.SessionsResponse, _ map[string]uint64) error {
			mu.Lock()
			if len(sess.LiveSessions) > 0 {
				names = append(names, sess.LiveSessions[0].CommonName)
			}
			mu.Unlock()
			return nil
		},
		offline:   func(string) {},
		setActive: func(bool) {},
	})

	sup := newStreamSupervisor()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sup.reconcile(ctx, conn)

	deadline := time.Now().Add(3 * time.Second)
	for {
		mu.Lock()
		n := len(names)
		mu.Unlock()
		if n >= 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("both live frames were not applied")
		}
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(150 * time.Millisecond)
	mu.Lock()
	got := append([]string{}, names...)
	mu.Unlock()
	if len(got) != 2 || got[0] != "amy" || got[1] != "bob" {
		t.Fatalf("applied frames %v, want [amy bob] with the stale rev 1 dropped", got)
	}
	cancel()
	waitStreamIdle(t, sup)
}

func TestLiveTickSuppressedWhileStreaming(t *testing.T) {
	conn, dir := newTrafficDB(t)
	h := NewHandler(auth.NewService(conn, dir))
	var calls atomic.Int32
	restore := setLiveCollect(func(*sql.DB) { calls.Add(1) })
	defer restore()

	telemetry.SetStreamsActive(true)
	defer telemetry.SetStreamsActive(false)

	h.liveTick(context.Background())
	if got := calls.Load(); got != 0 {
		t.Fatalf("live collect ran %d times while streams were active", got)
	}

	telemetry.SetStreamsActive(false)
	h.liveTick(context.Background())
	if got := calls.Load(); got != 1 {
		t.Fatalf("live collect ran %d times with no stream, want 1", got)
	}
}
