// Task 9: the user list reads real live-connection counts from the telemetry
// snapshot (backend) instead of the old
// hardcoded 0/false.
package tests

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// fakeSessionsAgent answers /sync/sessions with one live session per CN.
func fakeSessionsAgent(t *testing.T, commonNames ...string) *httptest.Server {
	t.Helper()
	sessions := ""
	for i, cn := range commonNames {
		if i > 0 {
			sessions += ","
		}
		sessions += fmt.Sprintf(`{"common_name":%q}`, cn)
	}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":{"live_sessions":[` + sessions + `]}}`))
	}))
	t.Cleanup(srv.Close)
	return srv
}

// TestUsersLiveConnections: a seeded snapshot (one live session for the user
// whose numeric CN matches their panel id) shows up as active_connections=1 /
// online=true, while a user with no sessions stays 0/false.
func TestUsersLiveConnections(t *testing.T) {
	env := newPanelEnv(t)
	// An idle window of 0 lets the cleanup poll below run immediately.
	t.Setenv("OVMANAGER_LIVE_IDLE_POLL_SECONDS", "0")

	seedUser := func(id int64, name string) {
		t.Helper()
		if _, err := env.conn.Exec(
			`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, is_active)
			 VALUES (?, ?, ?, NULL, 0, 0, '{}', 1, 1)`,
			id, fmt.Sprintf("eeee0000-0000-0000-0000-%012d", id), name,
		); err != nil {
			t.Fatalf("insert user %s: %v", name, err)
		}
	}
	seedUser(42, "alice")    // one live session on the node
	seedUser(43, "bob-idle") // the node reports no sessions for this one

	agent := fakeSessionsAgent(t, "42")
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	telemetry.CollectLiveSnapshot(env.conn)
	t.Cleanup(func() {
		// Poll once more with no nodes so the process-wide snapshot is empty
		// for every test that runs after this one.
		_, _ = env.conn.Exec(`DELETE FROM nodes`)
		telemetry.CollectLiveSnapshot(env.conn)
	})

	res, body := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/", env.token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("list = %d %v", res.StatusCode, body)
	}
	list, _ := body["data"].(map[string]any)
	rows, _ := list["users"].([]any)
	byName := map[string]map[string]any{}
	for _, row := range rows {
		u, _ := row.(map[string]any)
		byName[u["name"].(string)] = u
	}

	alice, ok := byName["alice"]
	if !ok {
		t.Fatalf("alice missing from %v", byName)
	}
	if alice["active_connections"] != float64(1) || alice["online"] != true {
		t.Errorf("alice live = %v, want 1 connection and online", alice)
	}

	bob, ok := byName["bob-idle"]
	if !ok {
		t.Fatalf("bob-idle missing from %v", byName)
	}
	if bob["active_connections"] != float64(0) || bob["online"] != false {
		t.Errorf("idle user live = %v, want 0 connections and offline", bob)
	}
}
