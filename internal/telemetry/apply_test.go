// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"database/sql"
	"fmt"
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

// drainEvents returns every queued bus event; Publish is synchronous, so a
// call that returned has already queued all of its events.
func drainEvents(ch chan Event) []Event {
	var out []Event
	for {
		select {
		case ev := <-ch:
			out = append(out, ev)
		default:
			return out
		}
	}
}

// kvMap turns an event's ordered pairs into a map for assertions.
func kvMap(ev Event) map[string]any {
	out := map[string]any{}
	for _, kv := range ev.Data {
		out[kv.Key] = kv.Val
	}
	return out
}

func pairsMap(v any) map[string]any {
	out := map[string]any{}
	pairs, _ := v.([]KV)
	for _, kv := range pairs {
		out[kv.Key] = kv.Val
	}
	return out
}

func TestApplyNodeSessionsPublishesLivePayload(t *testing.T) {
	conn := applyDB(t)
	ch := DefaultBus.Subscribe()
	defer DefaultBus.Unsubscribe(ch)
	if _, err := conn.Exec(`INSERT INTO User (id, uuid, name, total, used, node_usage, is_active) VALUES (3, 'uuid-carl', 'carl', 0, 0, '{}', 1)`); err != nil {
		t.Fatal(err)
	}
	if err := ApplyNodeSessions(conn, &node.Node{ID: 1, Name: "a"}, sessions("amy", "bob"), map[string]uint64{"amy": 4096, "carl": 512}); err != nil {
		t.Fatalf("apply: %v", err)
	}

	var usersLive, nodesLive map[string]any
	for _, ev := range drainEvents(ch) {
		switch ev.Topic {
		case "users.live":
			usersLive = kvMap(ev)
		case "nodes.live":
			nodesLive = kvMap(ev)
		}
	}
	if usersLive == nil || nodesLive == nil {
		t.Fatalf("live payloads missing: users=%v nodes=%v", usersLive, nodesLive)
	}
	if usersLive["op"] != "live" {
		t.Fatalf("users.live op = %v", usersLive["op"])
	}
	online := pairsMap(usersLive["online"])
	if online["amy"] != 1 || online["bob"] != 1 {
		t.Fatalf("users.live online = %v, want amy:1 bob:1", online)
	}
	usage := pairsMap(usersLive["usage"])
	if usage["amy"] != int64(4096) || usage["carl"] != int64(512) {
		t.Fatalf("users.live usage = %v, want amy:4096 carl:512", usage)
	}
	nodeOnline := pairsMap(nodesLive["online"])
	if nodeOnline["a"] != true {
		t.Fatalf("nodes.live online = %v, want a:true", nodeOnline)
	}
}

func TestApplyNodeSessionsSessionToasts(t *testing.T) {
	conn := applyDB(t)
	ch := DefaultBus.Subscribe()
	defer DefaultBus.Unsubscribe(ch)
	n := &node.Node{ID: 1, Name: "a"}

	// First snapshot is a silent baseline.
	if err := ApplyNodeSessions(conn, n, sessions("amy"), nil); err != nil {
		t.Fatal(err)
	}
	if got := sessionActions(drainEvents(ch)); len(got) != 0 {
		t.Fatalf("first snapshot announced sessions: %v", got)
	}

	// amy leaves, bob arrives.
	if err := ApplyNodeSessions(conn, n, sessions("bob"), nil); err != nil {
		t.Fatal(err)
	}
	got := sessionActions(drainEvents(ch))
	want := []string{"amy:disconnect", "bob:connect"}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("session events = %v, want %v", got, want)
	}

	// A new reject row announces once; the same row in the next snapshot does
	// not repeat.
	withReject := sessions("bob")
	withReject.Events = []node.EventEntry{{CN: "amy", Action: "max_logins", Reason: "max logins reached", Peer: "198.51.100.9:1", TS: 42}}
	if err := ApplyNodeSessions(conn, n, withReject, nil); err != nil {
		t.Fatal(err)
	}
	got = sessionActions(drainEvents(ch))
	if fmt.Sprint(got) != fmt.Sprint([]string{"amy:reject"}) {
		t.Fatalf("reject events = %v, want [amy:reject]", got)
	}
	if err := ApplyNodeSessions(conn, n, withReject, nil); err != nil {
		t.Fatal(err)
	}
	if got := sessionActions(drainEvents(ch)); len(got) != 0 {
		t.Fatalf("reject row announced twice: %v", got)
	}
}

// sessionActions renders users.session payloads as "name:action".
func sessionActions(events []Event) []string {
	var out []string
	for _, ev := range events {
		if ev.Topic != "users.session" {
			continue
		}
		kv := kvMap(ev)
		out = append(out, fmt.Sprintf("%v:%v", kv["name"], kv["action"]))
	}
	return out
}
