// Task 3: expired/depleted sweep (#5) + kick (#6). Tests first: the expired
// list mirrors the existing gating predicate (expiry past OR quota depleted),
// purge routes through the panel delete path (DeleteUserOnAllNodes fan-out
// included, per-node failure never aborts the batch) and kick kills live node
// sessions and reports how many were terminated (0 counts, still 200).
package tests

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeKickAgent answers POST /sync/user/{uid}/disconnect with a configurable
// kill payload and records the disconnect path.
func fakeKickAgent(t *testing.T, killed *[]string, mu *sync.Mutex, payload string) *httptest.Server {
	t.Helper()
	if payload == "" {
		payload = `{"success":true,"data":{"killed_sessions":0}}`
	}
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/disconnect") {
			if mu != nil {
				mu.Lock()
				*killed = append(*killed, r.URL.Path)
				mu.Unlock()
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(payload))
	}))
	t.Cleanup(srv.Close)
	return srv
}

// TestSweepRequires401 mirrors the existing guard on the new routes.
func TestSweepRequires401(t *testing.T) {
	_, base, _ := authedServer(t)
	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/api/users/expired"},
		{http.MethodPost, "/api/users/purge"},
		{http.MethodPost, "/api/users/aaaaaaaa-0000-0000-0000-000000000001/kick"},
	} {
		res, _ := doJSON(t, tc.method, base+tc.path, "", map[string]any{})
		res.Body.Close()
		if res.StatusCode != 401 {
			t.Fatalf("%s %s status = %d, want 401", tc.method, tc.path, res.StatusCode)
		}
	}
}

// TestUsersExpiredList: ExpiryDate < today or quota depleted are listed with
// the same JSON shape as the user list handler; everyone else is kept out.
func TestUsersExpiredList(t *testing.T) {
	env := newPanelEnv(t)
	past := "2000-01-01"
	future := time.Now().UTC().AddDate(0, 0, 30).Format("2006-01-02")
	seed := func(i int, uuid string, expiry string, total, used any) {
		t.Helper()
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, ?, ?, 0, '{}', 1, ?, 1)`, uuid, fmt.Sprintf("u-%02d", i), total, used, expiry,
		); err != nil {
			t.Fatalf("insert user %s: %v", uuid, err)
		}
	}
	seed(1, "aaaa0000-0000-0000-0000-000000000001", past, nil, nil)                 // expired
	seed(2, "aaaa0000-0000-0000-0000-000000000002", future, int64(100), int64(100)) // depleted
	seed(3, "aaaa0000-0000-0000-0000-000000000003", future, nil, nil)               // fine
	seed(4, "aaaa0000-0000-0000-0000-000000000004", past, int64(100), int64(0))     // expired too

	res, body := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/expired", env.token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("expired list = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data == nil {
		t.Fatalf("data missing: %v", body)
	}
	users, _ := data["users"].([]any)
	if len(users) != 3 {
		t.Errorf("users = %v (%d), want 3 expired/depleted rows", users, len(users))
	}
	if data["total"] != float64(3) {
		t.Errorf("total = %v, want 3", data["total"])
	}
	if data["page"] == nil || data["page_size"] == nil {
		t.Errorf("list shape incomplete: %v", data)
	}
	if len(users) > 0 {
		first, _ := users[0].(map[string]any)
		for _, key := range []string{"id", "name", "uuid", "expiry_date", "is_active", "active_connections", "online"} {
			if _, ok := first[key]; !ok {
				t.Errorf("expired list row missing key %q: %v", key, first)
			}
		}
	}
}

// TestUsersPurgeBulk: purge deletes the listed users panel-side, revokes their
// sessions first, and fans the delete out to nodes through the same path the
// single delete uses.
func TestUsersPurgeBulk(t *testing.T) {
	env := newPanelEnv(t)
	var deleted []string
	var mu sync.Mutex
	agent := fakeKickAgent(t, &deleted, &mu, "")
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	past := "2000-01-01"
	gone := "bbbb0000-0000-0000-0000-000000000001"
	keep := "bbbb0000-0000-0000-0000-000000000002"
	for _, u := range []struct{ uuid, name string }{{gone, "pu-gone"}, {keep, "pu-keep"}} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, ?, 1)`,
			u.uuid, u.name, past,
		); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/purge", env.token,
		map[string]any{"user_ids": []string{gone}})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("purge = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["deleted"] != float64(1) {
		t.Errorf("deleted = %v, want 1", data["deleted"])
	}
	skipped, _ := data["nodes_skipped"].([]any)
	for _, s := range skipped {
		if s == "n1" {
			t.Errorf("reachable node n1 wrongly reported as skipped: %v", skipped)
		}
	}
	var left int
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users WHERE uuid = ?`, gone).Scan(&left); err != nil || left != 0 {
		t.Errorf("purged row still present (left=%d err=%v)", left, err)
	}
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users WHERE uuid = ?`, keep).Scan(&left); err != nil || left != 1 {
		t.Errorf("untouched row changed (left=%d err=%v)", left, err)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(deleted) == 0 {
		t.Errorf("node agent received no DELETE /sync/user call for the purged user")
	}
}

// TestUsersPurgeValidatesAndRefusesEverything: an empty body is a 422; deleting
// every user is refused with the keep-one-user rule.
func TestUsersPurgeValidatesAndRefusesEverything(t *testing.T) {
	env := newPanelEnv(t)
	for i, u := range []string{"cccc0000-0000-0000-0000-000000000001", "cccc0000-0000-0000-0000-000000000002"} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, u, fmt.Sprintf("pu-%d", i+1),
		); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}

	res, _ := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/purge", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != 422 {
		t.Errorf("empty body status = %d, want 422", res.StatusCode)
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/purge", env.token,
		map[string]any{"user_ids": []string{
			"cccc0000-0000-0000-0000-000000000001", "cccc0000-0000-0000-0000-000000000002",
		}})
	res.Body.Close()
	if res.StatusCode != 409 {
		t.Fatalf("all-users purge status = %d %v, want 409", res.StatusCode, body)
	}
	if !strings.Contains(body["detail"].(string), "at least one user") {
		t.Errorf("detail = %v", body["detail"])
	}
	var left int
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&left); err != nil || left != 2 {
		t.Errorf("rows should be untouched on refusal (left=%d)", left)
	}
}

// TestUsersPurgeSurvivesUnreachableNode: one dead node is skipped, the count is
// reported, and the whole purge still succeeds.
func TestUsersPurgeSurvivesUnreachableNode(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "")
	env := newPanelEnv(t)
	insertTestNode(t, env.conn, 1, "dead", "127.0.0.1", 1, 1194, "")
	insertTestNode(t, env.conn, 2, "alive", "127.0.0.1", 2, 1194, "")

	gone := "dddd0000-0000-0000-0000-000000000001"
	kept := "dddd0000-0000-0000-0000-000000000002"
	for i, u := range []struct{ uuid string }{{gone}, {kept}} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, u.uuid, fmt.Sprintf("pu-%d", i+10),
		); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/purge", env.token,
		map[string]any{"user_ids": []string{gone}})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("purge = %d %v, want 200 despite an unreachable node", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["deleted"] != float64(1) {
		t.Errorf("deleted = %v, want 1", data["deleted"])
	}
	skipped, _ := data["nodes_skipped"].([]any)
	found := false
	for _, s := range skipped {
		if s == "dead" {
			found = true
		}
	}
	if !found {
		t.Errorf("dead node not reported in nodes_skipped: %v", skipped)
	}
	var left int
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users WHERE uuid = ?`, gone).Scan(&left); err != nil || left != 0 {
		t.Errorf("purged row still present (left=%d)", left)
	}
}

// TestUsersPurgeUnknownIDsAreIgnored: unknown uuids do not fail the batch.
func TestUsersPurgeUnknownIDsAreIgnored(t *testing.T) {
	env := newPanelEnv(t)
	for i, uuid := range []string{
		"eeee0000-0000-0000-0000-000000000001", "eeee0000-0000-0000-0000-000000000002",
	} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, uuid, fmt.Sprintf("pu-%d", i+20),
		); err != nil {
			t.Fatalf("insert user: %v", err)
		}
	}
	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/purge", env.token,
		map[string]any{"user_ids": []string{"eeee0000-0000-0000-0000-000000000001", "nope-0000"}})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("purge = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["deleted"] != float64(1) {
		t.Errorf("deleted = %v, want 1", data["deleted"])
	}
}

// TestUsersKickReturnsZeroWhenNoSessions: kick still succeeds (200) when there
// are no reachable signals of live sessions, reporting 0.
func TestUsersKickReturnsZeroWhenNoSessions(t *testing.T) {
	env := newPanelEnv(t)
	var killed []string
	var mu sync.Mutex
	agent := fakeKickAgent(t, &killed, &mu, `{"success":true}`)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	const uuid = "ffff0000-0000-0000-0000-000000000001"
	if _, err := env.conn.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (?, 'ku1', NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/kick", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("kick = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["kicked"] != float64(0) {
		t.Errorf("kicked = %v, want 0 (agent reported no kills)", data["kicked"])
	}
}

// TestUsersKickKillsLiveSessions: kick fans the disconnect out to every reachable
// node and reports how many sessions were terminated.
func TestUsersKickKillsLiveSessions(t *testing.T) {
	env := newPanelEnv(t)
	var kicked []string
	var mu sync.Mutex
	agent := fakeKickAgent(t, &kicked, &mu, `{"success":true,"data":{"removed_markers":["s1","s2"]}}`)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))
	insertTestNode(t, env.conn, 2, "n2", host, port, 1195, certPEM(t, agent))

	const uuid = "ffff0000-0000-0000-0000-000000000002"
	if _, err := env.conn.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (?, 'ku2', NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	var uid int64
	if err := env.conn.QueryRow(`SELECT id FROM users WHERE uuid = ?`, uuid).Scan(&uid); err != nil {
		t.Fatalf("select id: %v", err)
	}

	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/kick", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("kick = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["kicked"] != float64(4) {
		t.Errorf("kicked = %v, want 4 (both nodes report s1+s2)", data["kicked"])
	}
	wantPath := "/sync/user/" + fmt.Sprintf("%d", uid) + "/disconnect"
	mu.Lock()
	defer mu.Unlock()
	if len(kicked) != 2 {
		t.Errorf("agent disconnects = %v, want one per node (2)", kicked)
	}
	for _, p := range kicked {
		if p != wantPath {
			t.Errorf("disconnect path = %q, want %q", p, wantPath)
		}
	}
}

// TestUsersKickUnknownUser404 and zero-node environments still answer 200.
func TestUsersKickEdgeCases(t *testing.T) {
	env := newPanelEnv(t)
	res, _ := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/nope-0000-0000-0000-000000000001/kick", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != 404 {
		t.Errorf("unknown user status = %d, want 404", res.StatusCode)
	}

	// No nodes at all: kick is a no-op that still answers 200 with kicked=0.
	const uuid = "ffff0000-0000-0000-0000-000000000003"
	if _, err := env.conn.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (?, 'ku3', NULL, 0, 0, '{}', 1, '2000-01-01', 1)`, uuid,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	res, body := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/kick", env.token, map[string]any{})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("kick without nodes = %d %v", res.StatusCode, body)
	}
	if data := body["data"].(map[string]any); data["kicked"] != float64(0) {
		t.Errorf("kicked = %v, want 0", data["kicked"])
	}
}
