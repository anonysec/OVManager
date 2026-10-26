// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package tests

import (
	"database/sql"
	"net/http"
	"testing"
)

func seedNumericRouteUser(t *testing.T, conn *sql.DB, id int64, uuid, name string, active int64) {
	t.Helper()
	if _, err := conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (?, ?, ?, NULL, 64, 0, '{}', 2, '2099-01-01', ?)`,
		id, uuid, name, active,
	); err != nil {
		t.Fatalf("insert user %s: %v", name, err)
	}
}

func TestUsersNumericIDRoutesPreserveUUIDRoutesAndValidateIDs(t *testing.T) {
	env := newPanelEnv(t)
	const primaryUUID = "aaaaaaaa-0000-0000-0000-000000000042"
	seedNumericRouteUser(t, env.conn, 42, primaryUUID, "alice", 1)
	// A numeric-looking UUID is valid legacy data. The explicit /id/ form must
	// not change how the existing /users/{uuid}/... route resolves it.
	seedNumericRouteUser(t, env.conn, 43, "42", "numeric-uuid-user", 1)

	// Fixed route patterns remain distinct from the explicit numeric aliases.
	res, _ := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/traffic/top", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("top traffic status = %d, want 200", res.StatusCode)
	}

	res, body := doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/42/traffic", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric traffic = %d %v", res.StatusCode, body)
	}
	res, body = doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/42/sessions", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric sessions = %d %v", res.StatusCode, body)
	}
	if data, _ := body["data"].(map[string]any); data["username"] != "alice" {
		t.Errorf("numeric sessions resolved username = %v, want alice", data["username"])
	}

	// The unauthenticated alias is guarded exactly like the UUID route.
	res, _ = doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/42/sessions", "", nil)
	res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Errorf("unauthenticated numeric route status = %d, want 401", res.StatusCode)
	}

	for _, id := range []string{"abc", "0", "-1", "9223372036854775808", "999"} {
		res, _ = doJSON(t, http.MethodGet, env.srv.URL+"/api/users/id/"+id+"/sessions", env.token, nil)
		res.Body.Close()
		if res.StatusCode != http.StatusNotFound {
			t.Errorf("invalid/missing id %q status = %d, want 404", id, res.StatusCode)
		}
	}

	// The route aliases target the selected row, while the old UUID route still
	// resolves a numeric UUID as a UUID rather than as a row ID.
	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/42/status", env.token, map[string]any{"status": false})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric status update = %d %v", res.StatusCode, body)
	}
	var aliceActive, numericUUIDActive int64
	if err := env.conn.QueryRow(`SELECT is_active FROM users WHERE id = 42`).Scan(&aliceActive); err != nil {
		t.Fatal(err)
	}
	if err := env.conn.QueryRow(`SELECT is_active FROM users WHERE id = 43`).Scan(&numericUUIDActive); err != nil {
		t.Fatal(err)
	}
	if aliceActive != 0 || numericUUIDActive != 1 {
		t.Fatalf("numeric status changed id 42=%d, id 43=%d; want only id 42 disabled", aliceActive, numericUUIDActive)
	}

	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/42/status", env.token, map[string]any{"status": false})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("legacy numeric UUID status update = %d %v", res.StatusCode, body)
	}
	if err := env.conn.QueryRow(`SELECT is_active FROM users WHERE id = 43`).Scan(&numericUUIDActive); err != nil {
		t.Fatal(err)
	}
	if numericUUIDActive != 0 {
		t.Errorf("legacy /users/42 route did not resolve UUID '42': active = %d", numericUUIDActive)
	}

	// Mutation aliases include update (with/without trailing slash), reset,
	// extend, and delete; restore intentionally remains keyed by durable UUID.
	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/42/", env.token, map[string]any{"tag": "via-id"})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric update = %d %v", res.StatusCode, body)
	}
	var tag string
	if err := env.conn.QueryRow(`SELECT tag FROM users WHERE id = 42`).Scan(&tag); err != nil || tag != "via-id" {
		t.Fatalf("updated tag = %q, err=%v; want via-id", tag, err)
	}

	if _, err := env.conn.Exec(`UPDATE users SET used = 512, node_usage = '{"1":512}' WHERE id = 42`); err != nil {
		t.Fatal(err)
	}
	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/id/42/reset-usage", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric reset = %d %v", res.StatusCode, body)
	}
	var used int64
	if err := env.conn.QueryRow(`SELECT used FROM users WHERE id = 42`).Scan(&used); err != nil || used != 0 {
		t.Fatalf("numeric reset used = %d, err=%v; want 0", used, err)
	}

	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/id/42/extend", env.token, map[string]any{"days": 1})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric extend = %d %v", res.StatusCode, body)
	}

	res, body = doJSON(t, http.MethodDelete, env.srv.URL+"/api/users/id/42", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("numeric delete = %d %v", res.StatusCode, body)
	}
	res, body = doJSON(t, http.MethodPost, env.srv.URL+"/api/users/"+primaryUUID+"/restore", env.token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("UUID restore after numeric delete = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["uuid"] != primaryUUID || data["id"] == float64(42) {
		t.Errorf("restored user identity = %v; want preserved UUID and a newly assigned numeric ID", data)
	}

	res, _ = rawReq(t, http.MethodPost, env.srv.URL+"/api/users/id/42/restore", env.token, nil, "")
	if res.StatusCode != http.StatusNotFound {
		t.Errorf("numeric restore route status = %d, want 404 (UUID-only undo contract)", res.StatusCode)
	}
}

func TestUsersNumericIDRouteBoundariesAndAmbiguities(t *testing.T) {
	env := newPanelEnv(t)
	// Seed user with UUID "id" to test route disambiguation of /users/id/status
	seedNumericRouteUser(t, env.conn, 50, "id", "user-with-id-as-uuid", 1)
	seedNumericRouteUser(t, env.conn, 51, "regular-uuid-51", "user-51", 1)

	// 1. PUT /users/id/status updates status of user whose UUID is "id"
	res, body := doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/status", env.token, map[string]any{"status": false})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("PUT /users/id/status = %d %v, want 200 for user with uuid='id'", res.StatusCode, body)
	}
	var active int64
	if err := env.conn.QueryRow(`SELECT is_active FROM users WHERE uuid = 'id'`).Scan(&active); err != nil || active != 0 {
		t.Errorf("user with uuid='id' active = %d, want 0", active)
	}

	// 2. PUT /users/id/51 updates user 51
	res, body = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/51", env.token, map[string]any{"tag": "tag-51"})
	res.Body.Close()
	if res.StatusCode != http.StatusOK || body["success"] != true {
		t.Fatalf("PUT /users/id/51 = %d %v, want 200", res.StatusCode, body)
	}
	var tag string
	if err := env.conn.QueryRow(`SELECT tag FROM users WHERE id = 51`).Scan(&tag); err != nil || tag != "tag-51" {
		t.Errorf("user 51 tag = %q, want 'tag-51'", tag)
	}

	// 3. Invalid / out-of-range / malformed IDs on PUT /users/id/{id} return 404
	for _, badID := range []string{"0", "-1", "abc", "9223372036854775808", "99999"} {
		res, _ = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/"+badID, env.token, map[string]any{"tag": "x"})
		res.Body.Close()
		if res.StatusCode != http.StatusNotFound {
			t.Errorf("PUT /users/id/%s status = %d, want 404", badID, res.StatusCode)
		}
	}

	// 4. Arbitrary unknown 3-segment PUT path returns 404
	res, _ = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/foo/bar", env.token, map[string]any{"tag": "x"})
	res.Body.Close()
	if res.StatusCode != http.StatusNotFound {
		t.Errorf("PUT /users/foo/bar status = %d, want 404", res.StatusCode)
	}

	// 5. Unauthenticated PUT /users/id/51 is rejected with 401
	res, _ = doJSON(t, http.MethodPut, env.srv.URL+"/api/users/id/51", "", map[string]any{"tag": "x"})
	res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Errorf("unauthenticated PUT /users/id/51 status = %d, want 401", res.StatusCode)
	}
}
