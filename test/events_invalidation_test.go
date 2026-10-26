// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package tests

import (
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

func collectEventOps(ch chan telemetry.Event, topic string, timeout time.Duration) []string {
	var ops []string
	deadline := time.After(timeout)
	for {
		select {
		case ev := <-ch:
			if ev.Topic == topic {
				for _, kv := range ev.Data {
					if kv.Key == "op" {
						ops = append(ops, fmt.Sprint(kv.Val))
					}
				}
			}
		case <-deadline:
			return ops
		}
	}
}

func TestUserAndNodeMutationsPublishEventInvalidations(t *testing.T) {
	env := newPanelEnv(t)
	ch := telemetry.DefaultBus.Subscribe()
	defer telemetry.DefaultBus.Unsubscribe(ch)

	// 1. Create user -> publishes "users" op="create"
	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/", env.token, map[string]any{
		"name": "event_alice",
	})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("create user = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	uuid, _ := data["uuid"].(string)

	ops := collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "create" {
		t.Fatalf("create user events = %v, want ['create']", ops)
	}

	// 2. Update user -> publishes "users" op="update"
	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/"+uuid, env.token, map[string]any{
		"tag": "event-tag",
	})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("update user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "update" {
		t.Fatalf("update user events = %v, want ['update']", ops)
	}

	// 3. Status change -> publishes "users" op="status"
	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/"+uuid+"/status", env.token, map[string]any{
		"name":   "event_alice",
		"status": false,
	})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("status user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "status" {
		t.Fatalf("status user events = %v, want ['status']", ops)
	}

	// 4. Extend user -> publishes "users" op="extend"
	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/extend", env.token, map[string]any{
		"days": 10,
	})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("extend user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "extend" {
		t.Fatalf("extend user events = %v, want ['extend']", ops)
	}

	// 5. Reset usage -> publishes "users" op="reset-usage"
	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/reset-usage", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("reset-usage user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "reset-usage" {
		t.Fatalf("reset-usage user events = %v, want ['reset-usage']", ops)
	}

	// 6. Delete user (seed extra user first so count > 1) -> publishes "users" op="delete"
	seedNumericRouteUser(t, env.conn, 100, "extra-uuid-100", "extra_user", 1)
	res, body = doJSON(t, http.MethodDelete, env.srv.URL+"/api/users/"+uuid, env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("delete user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "delete" {
		t.Fatalf("delete user events = %v, want ['delete']", ops)
	}

	// 7. Restore user -> publishes "users" op="restore"
	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/restore", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("restore user = %d %v", res.StatusCode, body)
	}
	ops = collectEventOps(ch, "users", 50*time.Millisecond)
	if len(ops) != 1 || ops[0] != "restore" {
		t.Fatalf("restore user events = %v, want ['restore']", ops)
	}

	// 8. Delete node -> publishes "nodes" op="delete"
	insertTestNode(t, env.conn, 50, "node-50", "127.0.0.1", 2083, 1194, "")
	res, body = doJSON(t, http.MethodDelete, env.srv.URL+"/api/nodes/50", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("delete node = %d %v", res.StatusCode, body)
	}
	nodeOps := collectEventOps(ch, "nodes", 50*time.Millisecond)
	if len(nodeOps) != 1 || nodeOps[0] != "delete" {
		t.Fatalf("delete node events = %v, want ['delete']", nodeOps)
	}
}

func TestDiagnosticsHandlesDBQueryFailureGracefully(t *testing.T) {
	conn, dir := newTestDB(t)
	_ = dir

	if _, err := conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (1, 'u-1', 'test_user', NULL, 0, 0, '{}', 1, '2099-01-01', 1)`,
	); err != nil {
		t.Fatal(err)
	}

	// Drop nodes table to simulate a database query failure during getActiveNodes
	if _, err := conn.Exec(`DROP TABLE nodes`); err != nil {
		t.Fatal(err)
	}

	diag := node.GetUserSessionDiagnostics(1, conn, 8)
	if partial, _ := diag["partial"].(bool); !partial {
		t.Errorf("expected partial=true when database query fails, got %v", diag["partial"])
	}
	if rec, _ := diag["recommendation"].(string); rec != "Node diagnostics are incomplete; database query failed." {
		t.Errorf("expected db query failure recommendation, got %q", rec)
	}

	summary := node.LoginHealthSummary(conn, 8)
	if partial, _ := summary["partial"].(bool); !partial {
		t.Errorf("expected LoginHealthSummary partial=true when nodes query fails, got %v", summary["partial"])
	}

	// Drop users table to simulate both node and user queries failing
	if _, err := conn.Exec(`DROP TABLE users`); err != nil {
		t.Fatal(err)
	}
	summaryBoth := node.LoginHealthSummary(conn, 8)
	if partial, _ := summaryBoth["partial"].(bool); !partial {
		t.Errorf("expected LoginHealthSummary partial=true when both queries fail, got %v", summaryBoth["partial"])
	}
}
