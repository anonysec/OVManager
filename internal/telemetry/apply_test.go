// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"database/sql"
	"testing"

	"github.com/anonysec/OVManager/internal/node"
)

// applyDB is a clean snapshot plus two known users (amy, bob).
func applyDB(t *testing.T) *sql.DB {
	t.Helper()
	resetLiveState()
	conn := newCollectorDB(t)
	for _, u := range []struct {
		id   int64
		name string
	}{{1, "amy"}, {2, "bob"}} {
		if _, err := conn.Exec(
			`INSERT INTO User (id, uuid, name, total, used, node_usage, is_active) VALUES (?, ?, ?, 0, 0, '{}', 1)`,
			u.id, "uuid-"+u.name, u.name); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}
	return conn
}

func sessions(cns ...string) *node.SessionsResponse {
	out := &node.SessionsResponse{}
	for _, cn := range cns {
		out.LiveSessions = append(out.LiveSessions, node.SessionEntry{CommonName: cn})
	}
	return out
}

func TestApplyNodeSessionsMergesAcrossNodes(t *testing.T) {
	conn := applyDB(t)
	a := &node.Node{ID: 1, Name: "a"}
	b := &node.Node{ID: 2, Name: "b"}

	if err := ApplyNodeSessions(conn, a, sessions("amy"), nil); err != nil {
		t.Fatalf("apply a: %v", err)
	}
	if err := ApplyNodeSessions(conn, b, sessions("bob", "amy"), nil); err != nil {
		t.Fatalf("apply b: %v", err)
	}
	got := Connections()
	if got["amy"] != 2 || got["bob"] != 1 {
		t.Fatalf("connections = %v, want amy:2 bob:1", got)
	}

	// Re-applying one node replaces only that node's contribution.
	if err := ApplyNodeSessions(conn, a, sessions(), nil); err != nil {
		t.Fatalf("re-apply a: %v", err)
	}
	got = Connections()
	if got["amy"] != 1 || got["bob"] != 1 {
		t.Fatalf("connections after a shrank = %v, want amy:1 bob:1", got)
	}

	// A node that stops streaming as a whole drops out of the merge.
	MarkNodeOffline("a")
	got = Connections()
	if got["amy"] != 1 || got["bob"] != 1 {
		t.Fatalf("connections after a went offline = %v, want amy:1 bob:1", got)
	}
}

func TestApplyNodeSessionsStampsLastOnline(t *testing.T) {
	conn := applyDB(t)
	if err := ApplyNodeSessions(conn, &node.Node{ID: 1, Name: "a"}, sessions("amy", "2"), nil); err != nil {
		t.Fatalf("apply: %v", err)
	}
	for _, name := range []string{"amy", "bob"} {
		var last sql.NullString
		if err := conn.QueryRow(`SELECT last_online FROM User WHERE name = ?`, name).Scan(&last); err != nil {
			t.Fatal(err)
		}
		if !last.Valid || last.String == "" {
			t.Fatalf("user %s last_online = %v, want a stamp", name, last)
		}
	}
}

func TestApplyNodeSessionsPublishes(t *testing.T) {
	conn := applyDB(t)
	ch := DefaultBus.Subscribe()
	defer DefaultBus.Unsubscribe(ch)
	a := &node.Node{ID: 1, Name: "a"}

	if err := ApplyNodeSessions(conn, a, sessions("amy"), nil); err != nil {
		t.Fatalf("apply: %v", err)
	}
	// First apply: both the connection counts and the node status change.
	sawUsers, sawNodes := false, false
	for i := 0; i < 2; i++ {
		select {
		case ev := <-ch:
			for _, kv := range ev.Data {
				if ev.Topic == "users" && kv.Key == "op" && kv.Val == "connections" {
					sawUsers = true
				}
				if ev.Topic == "nodes" && kv.Key == "op" && kv.Val == "status" {
					sawNodes = true
				}
			}
		default:
		}
	}
	if !sawUsers || !sawNodes {
		t.Fatalf("published users=%v nodes=%v, want both", sawUsers, sawNodes)
	}

	// Expire the grace window, then a stream death flips the node offline
	// through the same publish path a failed poll uses.
	nodeAlerts.mu.Lock()
	nodeAlerts.graceUntil["a"] = 0
	nodeAlerts.mu.Unlock()
	MarkNodeOffline("a")
	flipped := false
	for {
		select {
		case ev := <-ch:
			if ev.Topic != "nodes" {
				continue
			}
			for _, kv := range ev.Data {
				if kv.Key == "op" && kv.Val == "status" {
					flipped = true
				}
			}
		default:
			if !flipped {
				t.Fatal("stream death did not publish a nodes status event")
			}
			return
		}
	}
}

func TestUsageEventDoesNotWriteDB(t *testing.T) {
	conn := applyDB(t)
	if _, err := conn.Exec(`UPDATE User SET used = 123, node_usage = '{"a":5}' WHERE name = 'amy'`); err != nil {
		t.Fatal(err)
	}
	if err := ApplyNodeSessions(conn, &node.Node{ID: 1, Name: "a"}, nil, map[string]uint64{"amy": 4096}); err != nil {
		t.Fatalf("apply usage: %v", err)
	}
	var used int64
	var nodeUsage string
	if err := conn.QueryRow(`SELECT used, node_usage FROM User WHERE name = 'amy'`).Scan(&used, &nodeUsage); err != nil {
		t.Fatal(err)
	}
	if used != 123 || nodeUsage != `{"a":5}` {
		t.Fatalf("billing columns changed by a usage event: used=%d node_usage=%q", used, nodeUsage)
	}
}

func TestMarkNodeOfflineGrace(t *testing.T) {
	conn := applyDB(t)
	a := &node.Node{ID: 1, Name: "a"}
	if err := ApplyNodeSessions(conn, a, sessions("amy"), nil); err != nil {
		t.Fatalf("apply: %v", err)
	}
	MarkNodeOffline("a")
	if !NodeOnline()["a"] {
		t.Fatal("a went offline before the grace window ended")
	}
	if got := Connections(); got["amy"] != 0 {
		t.Fatalf("connections = %v, want the dead node's sessions dropped", got)
	}

	nodeAlerts.mu.Lock()
	nodeAlerts.graceUntil["a"] = 0
	nodeAlerts.mu.Unlock()
	MarkNodeOffline("a")
	if NodeOnline()["a"] {
		t.Fatal("a stayed online after the grace window")
	}
}

func TestStreamsActiveFlag(t *testing.T) {
	resetLiveState()
	if StreamsActive() {
		t.Fatal("streams active on a clean state")
	}
	SetStreamsActive(true)
	if !StreamsActive() {
		t.Fatal("streams flag did not stick")
	}
	SetStreamsActive(false)
	if StreamsActive() {
		t.Fatal("streams flag did not clear")
	}
}
