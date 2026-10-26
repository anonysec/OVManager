// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package tests

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

func TestUsersSessionsReturnsLiveNodeDiagnostics(t *testing.T) {
	env := newPanelEnv(t)
	const uuid = "aaaa0000-0000-0000-0000-000000000042"
	if _, err := env.conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (42, ?, 'alice', NULL, 0, 0, '{}', 2, '2099-01-01', 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}

	agent := fakeSessionsAgent(t, "42-nodeA")
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "nodeA", host, port, 1194, certPEM(t, agent))

	res, body := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/"+uuid+"/sessions", env.token, nil)
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("sessions = %d %v", res.StatusCode, body)
	}
	data, ok := body["data"].(map[string]any)
	if !ok {
		t.Fatalf("sessions data = %T, want object", body["data"])
	}
	if data["active_connections"] != float64(1) || data["max_logins"] != float64(2) {
		t.Errorf("session summary = %v, want 1 active / 2 max", data)
	}
	if unavailable, ok := data["global_registry_error"].(string); !ok || unavailable == "" {
		t.Errorf("global registry error = %v, want explicit unavailable status", data["global_registry_error"])
	}

	nodes, ok := data["nodes"].([]any)
	if !ok || len(nodes) != 1 {
		t.Fatalf("nodes = %v, want one diagnostic node", data["nodes"])
	}
	nodeRow, ok := nodes[0].(map[string]any)
	if !ok || nodeRow["node"] != "nodeA" || nodeRow["live_count"] != float64(1) {
		t.Fatalf("node diagnostic = %v, want nodeA with one live session", nodes[0])
	}
	live, ok := nodeRow["live_sessions"].([]any)
	if !ok || len(live) != 1 {
		t.Fatalf("live sessions = %v, want one entry", nodeRow["live_sessions"])
	}
	session, ok := live[0].(map[string]any)
	if !ok || session["common_name"] != "42-nodeA" {
		t.Fatalf("live session = %v, want common_name 42", live[0])
	}

	res, numericBody := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/42/sessions", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || numericBody["success"] != true {
		t.Fatalf("numeric sessions = %d %v", res.StatusCode, numericBody)
	}
	numericData, _ := numericBody["data"].(map[string]any)
	if numericData["username"] != "alice" {
		t.Errorf("numeric session route resolved username = %v, want alice", numericData["username"])
	}
}

func TestUsersDisconnectAliasUsesKick(t *testing.T) {
	env := newPanelEnv(t)
	var paths []string
	var mu sync.Mutex
	agent := fakeKickAgent(t, &paths, &mu, `{"success":true,"data":{"killed_sessions":1}}`)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "nodeA", host, port, 1194, certPEM(t, agent))

	const uuid = "bbbb0000-0000-0000-0000-000000000042"
	if _, err := env.conn.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, is_active)
		 VALUES (?, 'alice', NULL, 0, 0, '{}', 2, 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	var userID int64
	if err := env.conn.QueryRow(`SELECT id FROM users WHERE uuid = ?`, uuid).Scan(&userID); err != nil {
		t.Fatalf("select user id: %v", err)
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/disconnect", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("disconnect alias = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["kicked"] != float64(1) {
		t.Errorf("kicked = %v, want one node-reported session", data["kicked"])
	}

	mu.Lock()
	defer mu.Unlock()
	if len(paths) != 1 || paths[0] != "/sync/user/"+fmt.Sprint(userID)+"/disconnect" {
		t.Errorf("node disconnect calls = %v, want one for user id %d", paths, userID)
	}
}

func TestUsersNumericIDKickUsesResolvedPanelID(t *testing.T) {
	env := newPanelEnv(t)
	var paths []string
	var mu sync.Mutex
	agent := fakeKickAgent(t, &paths, &mu, `{"success":true,"data":{"killed_sessions":1}}`)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "nodeA", host, port, 1194, certPEM(t, agent))
	const uuid = "cccc0000-0000-0000-0000-000000000042"
	if _, err := env.conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, is_active)
		 VALUES (42, ?, 'numeric-kick', NULL, 0, 0, '{}', 2, 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/id/42/kick", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric kick = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["kicked"] != float64(1) {
		t.Errorf("numeric kick count = %v, want one", data["kicked"])
	}

	mu.Lock()
	defer mu.Unlock()
	if len(paths) != 1 || paths[0] != "/sync/user/42/disconnect" {
		t.Errorf("numeric kick node calls = %v, want /sync/user/42/disconnect", paths)
	}
}

func TestUserSessionsDiagnosticsUsesOneNodeSnapshot(t *testing.T) {
	env := newPanelEnv(t)
	var calls int
	var mu sync.Mutex
	agent := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && r.URL.Path == "/sync/sessions" {
			mu.Lock()
			calls++
			mu.Unlock()
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":{"live_sessions":[{"common_name":"42-nodeA"}],"stale_markers":[],"auth_errors":7,"auth_errors_by_cn":{"42-nodeA":2}}}`))
	}))
	t.Cleanup(agent.Close)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "nodeA", host, port, 1194, certPEM(t, agent))
	const uuid = "dddd0000-0000-0000-0000-000000000042"
	if _, err := env.conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (42, ?, 'alice', NULL, 0, 0, '{}', 2, '2099-01-01', 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}

	res, body := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/42/sessions", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("sessions diagnostics = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	health, _ := data["health"].(map[string]any)
	if health["active_connections"] != float64(1) || health["auth_events"] != float64(2) {
		t.Errorf("health from shared snapshot = %v, want one active and two user auth events", health)
	}
	nodes, _ := data["nodes"].([]any)
	if len(nodes) != 1 {
		t.Fatalf("diagnostic nodes = %v, want one", data["nodes"])
	}
	if nodeRow, _ := nodes[0].(map[string]any); nodeRow["auth_events"] != float64(2) {
		t.Errorf("per-node user auth events = %v, want 2", nodeRow["auth_events"])
	}
	mu.Lock()
	defer mu.Unlock()
	if calls != 1 {
		t.Errorf("node session snapshot calls = %d, want one", calls)
	}
}
