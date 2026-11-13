package tests

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/internal/audit"
)

// authedServer boots a server with an owner row and returns base URL + token.
func authedServer(t *testing.T) (*sql.DB, string, string) {
	t.Helper()
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)
	token := loginToken(t, srv.URL, "admin", knownPassword)
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
	if data["is_active"] != true || data["max_logins"] != float64(0) {
		t.Errorf("defaults = %v", data)
	}
	if data["total"] != nil || data["used"] != nil || data["last_online"] != nil {
		t.Errorf("null fields = %v", data)
	}
	if uuid, _ := data["uuid"].(string); len(uuid) != 36 {
		t.Errorf("uuid = %v", data["uuid"])
	}
	if data["expiry_date"] != "" {
		t.Errorf("expiry_date = %v, want no expiry", data["expiry_date"])
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
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "bob", "expiry_date": "2030-01-01", "total": 100 * 1024 * 1024 * 1024})
	res.Body.Close()
	var uuid string
	if err := conn.QueryRow(`SELECT uuid FROM User WHERE name='bob'`).Scan(&uuid); err != nil {
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
	if data["expiry_date"] != "2030-01-11" || data["total"] != float64(100*1024*1024*1024+1024) {
		t.Errorf("extended = %v", data)
	}
}

// TestUsersStatusToggle mirrors PUT /{uuid}/status, including the
// activation_blocked refusal for expired users.
func TestUsersStatusToggle(t *testing.T) {
	conn, base, token := authedServer(t)
	if _, err := conn.Exec(`INSERT INTO User (uuid, name, total, used, node_usage, max_logins, expiry_date, is_active, last_node_usage)
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

	if _, err := conn.Exec(`INSERT INTO User (uuid, name, total, used, node_usage, max_logins, expiry_date, is_active, last_node_usage)
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

func uuidOf(t *testing.T, conn *sql.DB, name string) string {
	t.Helper()
	var uuid string
	if err := conn.QueryRow(`SELECT uuid FROM User WHERE name=?`, name).Scan(&uuid); err != nil {
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
	if err := conn.QueryRow(`SELECT total, tag FROM User WHERE uuid=?`, uuid).Scan(&total, &tag); err != nil {
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

	if _, err := conn.Exec(`UPDATE User SET used=1234, node_usage='{"1":900,"push_hash":{"1":"h"}}' WHERE uuid=?`, uuid); err != nil {
		t.Fatal(err)
	}
	res, got = doJSON(t, http.MethodPost, base+"/api/users/"+uuid+"/reset-usage", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "User usage reset successfully" {
		t.Fatalf("reset = %d %v", res.StatusCode, got)
	}
	var used int64
	var nodeUsage string
	if err := conn.QueryRow(`SELECT used, node_usage FROM User WHERE uuid=?`, uuid).Scan(&used, &nodeUsage); err != nil {
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

// TestUsersTopTraffic: GET /users/traffic/top ranks users by daily bytes.
func TestUsersTopTraffic(t *testing.T) {
	conn, base, token := authedServer(t)
	today := time.Now().UTC().Format("2006-01-02")
	ids := map[string]int64{}
	for _, n := range []string{"alice", "bob"} {
		res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": n})
		res.Body.Close()
		var id int64
		if err := conn.QueryRow(`SELECT id FROM User WHERE name=?`, n).Scan(&id); err != nil {
			t.Fatal(err)
		}
		ids[n] = id
	}
	for _, r := range []struct {
		id    int64
		bytes int64
	}{{ids["alice"], 3000}, {ids["bob"], 1000}} {
		if _, err := conn.Exec(`INSERT INTO UserTrafficDaily (user_id, day, bytes) VALUES (?,?,?)`, r.id, today, r.bytes); err != nil {
			t.Fatal(err)
		}
	}
	res, got := doJSON(t, http.MethodGet, base+"/api/users/traffic/top?days=30&limit=1", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 || got["msg"] != "Top traffic users retrieved" {
		t.Fatalf("top-traffic = %d %v", res.StatusCode, got)
	}
	rows, ok := got["data"].([]any)
	if !ok || len(rows) != 1 {
		t.Fatalf("top-traffic data = %v, want one row", got["data"])
	}
	first := rows[0].(map[string]any)
	if first["name"] != "alice" || first["bytes"] != float64(3000) {
		t.Errorf("top row = %v, want alice 3000", first)
	}
}

// TestUsersTrafficDailySeries: GET /users/{uuid}/traffic returns `days` as the
// zero-filled UserDailySeries window (the SPA asks ?days=14).
func TestUsersTrafficDailySeries(t *testing.T) {
	conn, base, token := authedServer(t)
	res, _ := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "erin"})
	res.Body.Close()
	uuid := uuidOf(t, conn, "erin")
	var id int64
	if err := conn.QueryRow(`SELECT id FROM User WHERE uuid=?`, uuid).Scan(&id); err != nil {
		t.Fatal(err)
	}
	today := time.Now().UTC().Format("2006-01-02")
	if _, err := conn.Exec(`INSERT INTO UserTrafficDaily (user_id, day, bytes) VALUES (?,?,?)`, id, today, 4096); err != nil {
		t.Fatal(err)
	}
	res, got := doJSON(t, http.MethodGet, base+"/api/users/"+uuid+"/traffic?days=14", token, nil)
	res.Body.Close()
	if res.StatusCode != 200 {
		t.Fatalf("traffic = %d %v", res.StatusCode, got)
	}
	days, ok := got["data"].(map[string]any)["days"].([]any)
	if !ok || len(days) != 14 {
		t.Fatalf("days = %v, want 14 entries", got["data"].(map[string]any)["days"])
	}
	last := days[len(days)-1].(map[string]any)
	if last["day"] != today || last["bytes"] != float64(4096) {
		t.Errorf("last day = %v, want %s 4096", last, today)
	}
}

// fakeUsageNode answers GET /sync/usage with pinned cumulative totals.
// The activity page is an audit trail only if the rows name the actor. Every
// state-changing operation must leave a row whose actor is the real
// username, not "system".
func TestUserMutationsWriteAnAuditRowWithTheActor(t *testing.T) {
	dir := t.TempDir()
	t.Setenv(audit.PathEnv, dir+"/audit.jsonl")
	conn, base, token := authedServer(t)
	// Two users: the panel refuses to delete the last one.
	for _, name := range []string{"audited", "keeper"} {
		res, body := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": name})
		if res.StatusCode != http.StatusOK {
			t.Fatalf("create %s: %d %s", name, res.StatusCode, body)
		}
	}
	var uuid string
	if err := conn.QueryRow(`SELECT uuid FROM User WHERE name = 'audited'`).Scan(&uuid); err != nil {
		t.Fatal(err)
	}
	res, body := doJSON(t, http.MethodDelete, base+"/api/users/"+uuid, token, nil)
	if res.StatusCode != http.StatusOK {
		t.Fatalf("delete: %d %s", res.StatusCode, body)
	}

	var actor, target string
	found := false
	for _, obj := range audit.ReadLines() {
		if obj["action"] == "User.Delete" {
			actor = fmt.Sprint(obj["actor"])
			target = fmt.Sprint(obj["target"])
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("no user.delete audit row")
	}
	if actor != "admin" {
		t.Errorf("actor = %q, want the acting username (admin)", actor)
	}
	if target != "audited" {
		t.Errorf("target = %q, want the deleted user's name", target)
	}
}

// The audit detail is rendered as text in the panel: it must never carry a
// secret.
func TestUserCreateAuditRowCarriesNoSecret(t *testing.T) {
	dir := t.TempDir()
	t.Setenv(audit.PathEnv, dir+"/audit.jsonl")
	_, base, token := authedServer(t)
	doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "quiet"})
	var detail string
	found := false
	for _, obj := range audit.ReadLines() {
		if obj["action"] == "User.Create" {
			b, _ := json.Marshal(obj)
			detail = string(b)
			found = true
			break
		}
	}
	if !found {
		t.Fatalf("no user.create audit row")
	}
	for _, secret := range []string{knownPassword, "password", "token"} {
		if strings.Contains(strings.ToLower(detail), secret) {
			t.Errorf("audit detail leaks %q: %s", secret, detail)
		}
	}
}

// The settings hint says "0 = unlimited" for the default device count. That
// has to survive all the way to a user created without an explicit
// max_logins — coercing it to 1 would silently limit every new user.
func TestCreateUsesTheUnlimitedDefault(t *testing.T) {
	conn, base, token := authedServer(t)
	if _, err := conn.Exec(
		`INSERT INTO Setting (id, default_days, default_traffic_gb, default_max_users) VALUES (1, 30, 100, 0)`,
	); err != nil {
		t.Fatal(err)
	}
	res, body := doJSON(t, http.MethodPost, base+"/api/users/", token, map[string]any{"name": "unlimited"})
	if res.StatusCode != http.StatusOK {
		t.Fatalf("create: %d %s", res.StatusCode, body)
	}
	var maxLogins int64
	if err := conn.QueryRow(`SELECT max_logins FROM User WHERE name = 'unlimited'`).Scan(&maxLogins); err != nil {
		t.Fatal(err)
	}
	if maxLogins != 0 {
		t.Errorf("max_logins = %d, want 0 (unlimited)", maxLogins)
	}
}
