package tests

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
)

// authedServer boots a server with an owner row and returns base URL + token.
func authedServer(t *testing.T) (*sql.DB, string, string) {
	t.Helper()
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)
	token := login(t, srv.URL, "admin", knownPassword)["access_token"].(string)
	return conn, srv.URL, token
}

// TestUsersRequires401 mirrors get_current_user on the protected router.
func TestUsersRequires401(t *testing.T) {
	_, base, _ := authedServer(t)
	res, body := doJSON(t, http.MethodGet, base+"/api/users/", "", nil)
	res.Body.Close()
	if res.StatusCode != 401 {
		t.Fatalf("status = %d, want 401", res.StatusCode)
	}
	if body["detail"] != "Could not validate credentials" {
		t.Errorf("detail = %v", body["detail"])
	}
}

// TestUsersCreateAndList mirrors POST /users/ (name normalisation, envelope,
// next-username stub) and GET /users/ (live-count fields).
func TestUsersCreateAndList(t *testing.T) {
	_, base, token := authedServer(t)

	res, body := doJSON(t, http.MethodPost, base+"/api/users/", token,
		map[string]any{"name": "John Doe"})
	res.Body.Close()
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("create = %d %v", res.StatusCode, body)
	}
	if body["msg"] != "User created successfully. VPN config will be generated on first download." {
		t.Errorf("msg = %v", body["msg"])
	}
	data := body["data"].(map[string]any)
	if data["name"] != "John_Doe" {
		t.Errorf("name = %v, want John_Doe (spaces normalised)", data["name"])
	}
	if data["is_active"] != true || data["max_logins"] != float64(1) {
		t.Errorf("defaults = %v", data)
	}
	if data["total"] != nil || data["used"] != nil || data["last_online"] != nil {
		t.Errorf("null fields = %v", data)
	}
	if uuid, _ := data["uuid"].(string); len(uuid) != 36 {
		t.Errorf("uuid = %v", data["uuid"])
	}
	wantExpiry := time.Now().UTC().AddDate(0, 0, 30).Format("2006-01-02")
	if data["expiry_date"] != wantExpiry {
		t.Errorf("expiry_date = %v, want %v", data["expiry_date"], wantExpiry)
	}

	res, body = doJSON(t, http.MethodGet, base+"/api/users/", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 {
		t.Fatalf("list status = %d", res.StatusCode)
	}
	list := body["data"].(map[string]any)
	if list["total"] != float64(1) || list["page"] != float64(1) || list["page_size"] != float64(1) {
		t.Errorf("pagination = %v", list)
	}
	users := list["users"].([]any)
	first := users[0].(map[string]any)
	if first["active_connections"] != float64(0) || first["online"] != false {
		t.Errorf("live fields = %v", first)
	}
	for _, key := range []string{"id", "name", "is_active", "total", "used", "max_logins", "expiry_date", "uuid", "last_online", "tag", "active_connections", "online"} {
		if _, ok := first[key]; !ok {
			t.Errorf("missing key %q in user payload", key)
		}
	}

	res, body = doJSON(t, http.MethodGet, base+"/api/users/next-username", token, nil)
	res.Body.Close()
	if body["success"] != false || body["msg"] != "No username prefix configured" {
		t.Errorf("next-username = %v", body)
	}
}

// TestUsersCreateDuplicate409 mirrors the explicit 409 in routers/users.py.
func TestUsersCreateDuplicate409(t *testing.T) {
	_, base, token := authedServer(t)
	for i := 0; i < 2; i++ {
		res, body := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "alice"})
		res.Body.Close()
		if i == 0 && res.StatusCode != 200 {
			t.Fatalf("first create = %d", res.StatusCode)
		}
		if i == 1 {
			if res.StatusCode != 409 {
				t.Fatalf("duplicate status = %d, want 409", res.StatusCode)
			}
			if body["detail"] != "User with this name already exists" {
				t.Errorf("detail = %v", body["detail"])
			}
		}
	}
}

// TestUsersValidation422 mirrors the Pydantic min_length on CreateUser.name.
func TestUsersValidation422(t *testing.T) {
	_, base, token := authedServer(t)
	res, body := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "ab"})
	res.Body.Close()
	if res.StatusCode != 422 {
		t.Fatalf("status = %d, want 422", res.StatusCode)
	}
	if _, ok := body["detail"].([]any); !ok {
		t.Errorf("detail = %v, want FastAPI error list", body["detail"])
	}
}

// TestUsersNotFound404 covers the shared "User not found" 404 on every
// per-UUID route.
func TestUsersNotFound404(t *testing.T) {
	_, base, token := authedServer(t)
	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/api/users/nope/traffic"},
		{http.MethodPut, "/api/users/nope"},
		{http.MethodPut, "/api/users/nope/status"},
		{http.MethodGet, "/api/users/nope/sessions"},
		{http.MethodPost, "/api/users/nope/disconnect"},
		{http.MethodDelete, "/api/users/nope"},
		{http.MethodPost, "/api/users/nope/reset-usage"},
		{http.MethodPost, "/api/users/nope/extend"},
	} {
		var body any
		switch tc.path {
		case "/api/users/nope/status":
			body = map[string]any{"name": "nope", "status": true}
		case "/api/users/nope/extend":
			body = map[string]any{"days": 1, "bytes": 0}
		case "/api/users/nope":
			body = map[string]any{"name": "nope"}
		}
		res, got := doJSON(t, tc.method, base+tc.path, token, body)
		res.Body.Close()
		if res.StatusCode != 404 || got["detail"] != "User not found" {
			t.Errorf("%s %s = %d %v, want 404 User not found", tc.method, tc.path, res.StatusCode, got["detail"])
		}
	}
}

// TestUsersExtend mirrors POST /{uuid}/extend: 422 when both are zero, else
// expiry/quota move.
func TestUsersExtend(t *testing.T) {
	conn, base, token := authedServer(t)
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "bob", "expiry_date": "2030-01-01"})
	res.Body.Close()
	var uuid string
	if err := conn.QueryRow(`SELECT uuid FROM users WHERE name='bob'`).Scan(&uuid); err != nil {
		t.Fatal(err)
	}

	res, got := doJSON(t, http.MethodPost, base+"/api/users/"+uuid+"/extend", token, map[string]any{"days": 0, "bytes": 0})
	res.Body.Close()
	if res.StatusCode != 422 || got["detail"] != "days or bytes must be greater than 0" {
		t.Fatalf("zero extend = %d %v", res.StatusCode, got["detail"])
	}

	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuid+"/extend", token, map[string]any{"days": 10, "bytes": 1024})
	res.Body.Close()
	if res.StatusCode != 200 || got["success"] != true || got["msg"] != "User updated" {
		t.Fatalf("extend = %d %v", res.StatusCode, got)
	}
	data := got["data"].(map[string]any)
	if data["expiry_date"] != "2030-01-11" || data["total"] != float64(1024) {
		t.Errorf("extended = %v", data)
	}
}

// TestUsersStatusToggle mirrors PUT /{uuid}/status, including the
// activation_blocked refusal for expired users.
func TestUsersStatusToggle(t *testing.T) {
	conn, base, token := authedServer(t)
	if _, err := conn.Exec(`INSERT INTO users (uuid, name, total, used, node_usage, max_logins, expiry_date, is_active, last_node_usage)
		VALUES ('u-expired','expired',NULL,0,'{}',1,'2020-01-01',0,0)`); err != nil {
		t.Fatal(err)
	}
	res, got := doJSON(t, http.MethodPut, base+"/api/users/u-expired/status", token,
		map[string]any{"name": "expired", "status": true})
	res.Body.Close()
	if res.StatusCode != 200 || got["success"] != false {
		t.Fatalf("blocked activation = %d %v", res.StatusCode, got)
	}
	if got["msg"] != "Cannot activate: user is expired" {
		t.Errorf("msg = %v", got["msg"])
	}

	if _, err := conn.Exec(`INSERT INTO users (uuid, name, total, used, node_usage, max_logins, expiry_date, is_active, last_node_usage)
		VALUES ('u-ok','ok',NULL,0,'{}',1,'2030-01-01',0,0)`); err != nil {
		t.Fatal(err)
	}
	res, got = doJSON(t, http.MethodPut, base+"/api/users/u-ok/status", token,
		map[string]any{"name": "ok", "status": true})
	res.Body.Close()
	if res.StatusCode != 200 || got["success"] != true || got["msg"] != "Changed user status successfully" {
		t.Fatalf("activation = %d %v", res.StatusCode, got)
	}
}

// TestUsersDeleteRestore covers DELETE (msg shape) and the Undo path:
// 410 outside the window, 200 on restore, 409 once present again.
func TestUsersDeleteRestore(t *testing.T) {
	conn, base, token := authedServer(t)
	for _, n := range []string{"one", "two"} {
		res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": n})
		res.Body.Close()
	}
	uuidTwo := uuidOf(t, conn, "two")
	res, got := doJSON(t, http.MethodDelete, base+"/api/users/"+uuidTwo, token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "User deleted successfully" {
		t.Fatalf("delete = %d %v", res.StatusCode, got)
	}
	// Restore unknown UUID → 410 (Undo window expired).
	res, got = doJSON(t, http.MethodPost, base+"/api/users/unknown-uuid/restore", token, nil)
	res.Body.Close()
	if res.StatusCode != 410 || !strings.Contains(got["detail"].(string), "Undo window expired") {
		t.Fatalf("restore unknown = %d %v", res.StatusCode, got["detail"])
	}
	// Restore the deleted row (original UUID survives).
	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuidTwo+"/restore", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["success"] != true {
		t.Fatalf("restore = %d %v", res.StatusCode, got)
	}
	if got["data"].(map[string]any)["uuid"] != uuidTwo {
		t.Errorf("restored uuid = %v, want %v", got["data"].(map[string]any)["uuid"], uuidTwo)
	}
	// A consumed entry can no longer be undone (pops on success).
	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuidTwo+"/restore", token, nil)
	res.Body.Close()
	if res.StatusCode != 410 {
		t.Fatalf("repeat restore = %d %v, want 410", res.StatusCode, got["detail"])
	}

	// 409 "User already exists": the UUID reappears while undo is still armed.
	uuidOne := uuidOf(t, conn, "one")
	res, _ = doJSON(t, http.MethodDelete, base+"/api/users/"+uuidOne, token, nil)
	res.Body.Close()
	if _, err := conn.Exec(`INSERT INTO users (uuid, name, total, used, node_usage, last_node_usage, max_logins, expiry_date, is_active)
		VALUES (?, 'revived', NULL, 0, '{}', 0, 1, '2030-01-01', 1)`, uuidOne); err != nil {
		t.Fatal(err)
	}
	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuidOne+"/restore", token, nil)
	res.Body.Close()
	if res.StatusCode != 409 || got["detail"] != "User already exists" {
		t.Fatalf("restore over existing = %d %v", res.StatusCode, got["detail"])
	}
}

func uuidOf(t *testing.T, conn *sql.DB, name string) string {
	t.Helper()
	var uuid string
	if err := conn.QueryRow(`SELECT uuid FROM users WHERE name=?`, name).Scan(&uuid); err != nil {
		t.Fatalf("uuid of %s: %v", name, err)
	}
	return uuid
}

// TestUsersDeleteLast409 mirrors the "keep at least one user" guard.
func TestUsersDeleteLast409(t *testing.T) {
	conn, base, token := authedServer(t)
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "solo"})
	res.Body.Close()
	res, got := doJSON(t, http.MethodDelete, base+"/api/users/"+uuidOf(t, conn, "solo"), token, nil)
	res.Body.Close()
	if res.StatusCode != 409 {
		t.Fatalf("status = %d, want 409", res.StatusCode)
	}
	if got["detail"] != "You must keep at least one user — create another before deleting this one" {
		t.Errorf("detail = %v", got["detail"])
	}
}

// TestUsersUpdate mirrors PUT /{uuid} (200 "User updated successfully").
func TestUsersUpdate(t *testing.T) {
	conn, base, token := authedServer(t)
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "carol"})
	res.Body.Close()
	uuid := uuidOf(t, conn, "carol")
	res, got := doJSON(t, http.MethodPut, base+"/api/users/"+uuid, token,
		map[string]any{"name": "carol", "total": 5000, "tag": " vip "})
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "User updated successfully" {
		t.Fatalf("update = %d %v", res.StatusCode, got)
	}
	var total int64
	var tag sql.NullString
	if err := conn.QueryRow(`SELECT total, tag FROM users WHERE uuid=?`, uuid).Scan(&total, &tag); err != nil {
		t.Fatal(err)
	}
	if total != 5000 || tag.String != "vip" {
		t.Errorf("row = %d %v, want 5000 vip", total, tag.String)
	}
}

// TestUsersTrafficAndReset covers the local (node-free) part of the traffic
// and reset-usage routes.
func TestUsersTrafficAndReset(t *testing.T) {
	conn, base, token := authedServer(t)
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "dave"})
	res.Body.Close()
	uuid := uuidOf(t, conn, "dave")

	res, got := doJSON(t, http.MethodGet, base+"/api/users/"+uuid+"/traffic", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "User traffic history retrieved" {
		t.Fatalf("traffic = %d %v", res.StatusCode, got)
	}

	if _, err := conn.Exec(`UPDATE users SET used=1234, node_usage='{"1":900,"push_hash":{"1":"h"}}' WHERE uuid=?`, uuid); err != nil {
		t.Fatal(err)
	}
	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuid+"/reset-usage", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "User usage reset successfully" {
		t.Fatalf("reset = %d %v", res.StatusCode, got)
	}
	var used int64
	var nodeUsage string
	if err := conn.QueryRow(`SELECT used, node_usage FROM users WHERE uuid=?`, uuid).Scan(&used, &nodeUsage); err != nil {
		t.Fatal(err)
	}
	if used != 0 {
		t.Errorf("after reset: used=%d, want 0", used)
	}
	state := map[string]any{}
	if err := json.Unmarshal([]byte(nodeUsage), &state); err != nil {
		t.Fatalf("node_usage %q: %v", nodeUsage, err)
	}
	if state["1"] != float64(900) {
		t.Errorf(`baseline dropped: node_usage["1"]=%v, want 900`, state["1"])
	}
	if _, ok := state["push_hash"]; !ok {
		t.Errorf("push_hash dropped: %v", state)
	}
	if state["__reseed"] != true {
		t.Errorf("reseed marker missing: %v", state)
	}
}

// fakeUsageNode answers GET /sync/usage with pinned cumulative totals.
func fakeUsageNode(t *testing.T, totals map[string]any) *httptest.Server {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		body, _ := json.Marshal(map[string]any{
			"success": true,
			"data":    map[string]any{"totals": totals},
		})
		_, _ = w.Write(body)
	}))
	t.Cleanup(srv.Close)
	return srv
}

// TestUsersResetReseedsBaselines: a reset keeps the per-node baseline and marks
// the user for reseed, so the next traffic pass seeds delta 0 (no re-bill of
// bytes already counted) and clears the marker (design §4.6).
func TestUsersResetReseedsBaselines(t *testing.T) {
	env := newPanelEnv(t)
	res, _ := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/", env.token, map[string]any{"name": "user"})
	res.Body.Close()
	uuid := uuidOf(t, env.conn, "user")
	if _, err := env.conn.Exec(`UPDATE users SET used=999, node_usage='{"1":500,"push_hash":{"1":"x"}}' WHERE uuid=?`, uuid); err != nil {
		t.Fatal(err)
	}
	res, got := doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+uuid+"/reset-usage", env.token, nil)
	res.Body.Close()
	if res.StatusCode != 200 {
		t.Fatalf("reset = %d %v", res.StatusCode, got)
	}

	agent := fakeUsageNode(t, map[string]any{"user": int64(600)})
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	node.SyncTraffic(env.conn)

	var used int64
	var raw string
	if err := env.conn.QueryRow(`SELECT used, node_usage FROM users WHERE uuid=?`, uuid).Scan(&used, &raw); err != nil {
		t.Fatal(err)
	}
	if used != 0 {
		t.Errorf("used = %d, want 0 (reseed must not re-bill)", used)
	}
	state := map[string]any{}
	if err := json.Unmarshal([]byte(raw), &state); err != nil {
		t.Fatalf("node_usage %q: %v", raw, err)
	}
	if state["1"] != float64(600) {
		t.Errorf(`node_usage["1"] = %v, want 600 (reseeded baseline)`, state["1"])
	}
	if _, ok := state["__reseed"]; ok {
		t.Errorf("marker not cleared: %v", state)
	}
	if _, ok := state["push_hash"]; !ok {
		t.Errorf("push_hash lost after pass: %v", state)
	}
}
