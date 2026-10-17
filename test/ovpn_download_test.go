// Task 6 (rescoped): .ovpn client issuance parity. The download path already
// exists (panel pulls the profile from a node agent and rewrites the `remote`
// lines); these tests pin its rewrite semantics, the handler's gating (active +
// quota, now also expiry) and the user-delete fan-out to nodes.
package tests

import (
	"database/sql"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
)

// ovpnProfile is a node-native profile: one `remote` line naming the node's own
// address. injectRemoteLines must keep it and add the panel/fallback remotes.
const ovpnProfile = "client\ndev tun\nremote node-native.example 1194\n<ca>\nMIIB\n</ca>\n"

// fakeOVPNAgent answers node-agent calls: it serves the profile for every
// /sync/download/ovpn/{uid} request and records DELETE /sync/user/{uid} calls.
func fakeOVPNAgent(t *testing.T, profile string, deleted *[]string, mu *sync.Mutex) *httptest.Server {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasPrefix(r.URL.Path, "/sync/download/ovpn/"):
			w.Header().Set("Content-Type", "application/x-openvpn-profile")
			_, _ = w.Write([]byte(profile))
		case r.Method == http.MethodDelete && strings.HasPrefix(r.URL.Path, "/sync/user/"):
			if mu != nil {
				mu.Lock()
				*deleted = append(*deleted, r.URL.Path)
				mu.Unlock()
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"success":true}`))
		default:
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"success":true}`))
		}
	}))
	t.Cleanup(srv.Close)
	return srv
}

// insertTestNode adds a node row pointing at addr:port with an optional pin.
func insertTestNode(t *testing.T, conn *sql.DB, id int64, name, address string, port, ovpnPort int, pin string) {
	t.Helper()
	var ca any
	if pin != "" {
		ca = pin
	}
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca)
		 VALUES (?, ?, ?, '', 'tcp', ?, ?, 'k', 1, ?)`,
		id, name, address, ovpnPort, port, ca,
	); err != nil {
		t.Fatalf("insert node %s: %v", name, err)
	}
}

// TestDownloadOVPNInjectsPanelDomainAndFallbacks: with panel_domain set the
// primary remote is the panel domain + node ovpn_port, followed by one fallback
// remote per other node; the node-native remote line is kept.
func TestDownloadOVPNInjectsPanelDomainAndFallbacks(t *testing.T) {
	env := newPanelEnv(t)
	agent := fakeOVPNAgent(t, ovpnProfile, nil, nil)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))
	insertTestNode(t, env.conn, 2, "n2", "203.0.113.9", 2083, 443, "")
	if _, err := env.conn.Exec(`INSERT INTO settings (id, panel_domain) VALUES (1, 'panel.example.com')`); err != nil {
		t.Fatalf("settings: %v", err)
	}

	out := node.DownloadOVPNClient(7, 1, env.conn)
	if out == nil {
		t.Fatalf("DownloadOVPNClient = nil, want rewritten profile")
	}
	s := string(out)
	if !strings.Contains(s, "remote panel.example.com 1194") {
		t.Errorf("missing panel-domain primary remote:\n%s", s)
	}
	if !strings.Contains(s, "remote 203.0.113.9 443") {
		t.Errorf("missing per-other-node fallback remote:\n%s", s)
	}
	if !strings.Contains(s, "remote node-native.example 1194") {
		t.Errorf("node-native remote line was dropped:\n%s", s)
	}
	if strings.Index(s, "remote panel.example.com 1194") > strings.Index(s, "remote node-native.example 1194") {
		t.Errorf("panel-domain remote should precede the node-native line:\n%s", s)
	}
}

// TestDownloadOVPNKeepsNodeAddressWithoutPanelDomain: with panel_domain empty the
// node-native remote is retained (a warning is acceptable) and only the fallback
// remotes are appended.
func TestDownloadOVPNKeepsNodeAddressWithoutPanelDomain(t *testing.T) {
	env := newPanelEnv(t)
	agent := fakeOVPNAgent(t, ovpnProfile, nil, nil)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))
	insertTestNode(t, env.conn, 2, "n2", "203.0.113.9", 2083, 443, "")

	out := node.DownloadOVPNClient(7, 1, env.conn)
	if out == nil {
		t.Fatalf("DownloadOVPNClient = nil, want profile")
	}
	s := string(out)
	if !strings.Contains(s, "remote node-native.example 1194") {
		t.Errorf("node-native remote line should be retained when no panel domain:\n%s", s)
	}
	if !strings.Contains(s, "remote 203.0.113.9 443") {
		t.Errorf("fallback remote missing:\n%s", s)
	}
	if strings.Contains(s, "panel.example.com") {
		t.Errorf("no panel domain is set, but one was injected:\n%s", s)
	}
}

// TestDownloadOVPNGating pins the handler's per-user gates: active+under-quota
// passes, inactive/over-quota/expired are refused with FastAPI-shaped 403s.
func TestDownloadOVPNGating(t *testing.T) {
	env := newPanelEnv(t)
	agent := fakeOVPNAgent(t, ovpnProfile, nil, nil)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	future := time.Now().UTC().AddDate(0, 0, 5).Format("2006-01-02")
	seed := func(uuid string, active int, total, used any, expiry string) {
		t.Helper()
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, tag)
			 VALUES (?, ?, ?, ?, 0, '{}', 1, ?, ?, NULL)`,
			uuid, "u-"+uuid[:4], total, used, expiry, active,
		); err != nil {
			t.Fatalf("insert user %s: %v", uuid, err)
		}
	}
	const (
		activeUUID   = "aaaaaaaa-0000-0000-0000-000000000001"
		inactiveUUID = "bbbbbbbb-0000-0000-0000-000000000002"
		overUUID     = "cccccccc-0000-0000-0000-000000000003"
		expiredUUID  = "dddddddd-0000-0000-0000-000000000004"
	)
	seed(activeUUID, 1, int64(1_000_000_000), int64(0), future)
	seed(inactiveUUID, 0, int64(1_000_000_000), int64(0), future)
	seed(overUUID, 1, int64(100), int64(100), future)
	seed(expiredUUID, 1, int64(1_000_000_000), int64(0), "2000-01-01")

	cases := []struct {
		name     string
		uuid     string
		wantCode int
		wantBody string
	}{
		{"active under quota", activeUUID, http.StatusOK, ""},
		{"inactive", inactiveUUID, http.StatusForbidden, "User account is not active"},
		{"over quota", overUUID, http.StatusForbidden, "User traffic limit reached"},
		{"expired", expiredUUID, http.StatusForbidden, "User account has expired"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			res, raw := rawReq(t, http.MethodGet, env.srv.URL+"/api/nodes/ovpn/"+tc.uuid+"/1", env.token, nil, "")
			if res.StatusCode != tc.wantCode {
				t.Fatalf("status = %d, want %d (body %s)", res.StatusCode, tc.wantCode, raw)
			}
			if tc.wantBody != "" && !strings.Contains(string(raw), tc.wantBody) {
				t.Errorf("body = %s, want to contain %q", raw, tc.wantBody)
			}
			if tc.wantCode == http.StatusOK && !strings.Contains(string(raw), "remote node-native.example 1194") {
				t.Errorf("200 body is not a rewritten profile:\n%s", raw)
			}
		})
	}
}

// TestDeleteUserFansOutToNodes: deleting a panel user also evicts it from every
// reachable node.
func TestDeleteUserFansOutToNodes(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "")
	env := newPanelEnv(t)
	var deleted []string
	var mu sync.Mutex
	agent := fakeOVPNAgent(t, ovpnProfile, &deleted, &mu)
	host, port := hostPort(t, agent.URL)
	insertTestNode(t, env.conn, 1, "n1", host, port, 1194, certPEM(t, agent))

	for _, u := range []struct{ uuid, name string }{
		{"eeeeeeee-0000-0000-0000-000000000001", "keep"},
		{"eeeeeeee-0000-0000-0000-000000000002", "gone"},
	} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, NULL, 1)`, u.uuid, u.name,
		); err != nil {
			t.Fatalf("insert user %s: %v", u.name, err)
		}
	}

	res, raw := rawReq(t, http.MethodDelete, env.srv.URL+"/api/users/eeeeeeee-0000-0000-0000-000000000002", env.token, nil, "")
	if res.StatusCode != http.StatusOK {
		t.Fatalf("delete status = %d, want 200 (body %s)", res.StatusCode, raw)
	}
	var left int
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users WHERE name = 'gone'`).Scan(&left); err != nil {
		t.Fatalf("count: %v", err)
	}
	if left != 0 {
		t.Errorf("panel user row still present after delete")
	}
	mu.Lock()
	defer mu.Unlock()
	if len(deleted) == 0 {
		t.Fatalf("node agent received no DELETE /sync/user call")
	}
}

// TestDeleteUserSurvivesUnreachableNode: a node the panel cannot reach must not
// block the panel-side delete (log + continue, no stuck row).
func TestDeleteUserSurvivesUnreachableNode(t *testing.T) {
	t.Setenv("NODE_TLS_INSECURE_FALLBACK", "")
	env := newPanelEnv(t)
	// 127.0.0.1:1 is a closed port: the fan-out call fails fast.
	insertTestNode(t, env.conn, 1, "dead", "127.0.0.1", 1, 1194, "")

	for _, u := range []struct{ uuid, name string }{
		{"ffffffff-0000-0000-0000-000000000001", "keep2"},
		{"ffffffff-0000-0000-0000-000000000002", "gone2"},
	} {
		if _, err := env.conn.Exec(
			`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
			 VALUES (?, ?, NULL, 0, 0, '{}', 1, NULL, 1)`, u.uuid, u.name,
		); err != nil {
			t.Fatalf("insert user %s: %v", u.name, err)
		}
	}

	res, raw := rawReq(t, http.MethodDelete, env.srv.URL+"/api/users/ffffffff-0000-0000-0000-000000000002", env.token, nil, "")
	if res.StatusCode != http.StatusOK {
		t.Fatalf("delete status = %d, want 200 despite unreachable node (body %s)", res.StatusCode, raw)
	}
	body, _ := io.ReadAll(res.Body)
	_ = body
	var left int
	if err := env.conn.QueryRow(`SELECT COUNT(*) FROM users WHERE name = 'gone2'`).Scan(&left); err != nil {
		t.Fatalf("count: %v", err)
	}
	if left != 0 {
		t.Errorf("panel user row still present after delete with an unreachable node")
	}
}
