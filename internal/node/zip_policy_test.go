package node

import (
	"archive/zip"
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// TestDownloadAllPushesPolicyBeforeProfiles: the ZIP path must push the
// effective per-user policy before fetching profiles, like single downloads.
func TestDownloadAllPushesPolicyBeforeProfiles(t *testing.T) {
	conn := newTrafficDB(t)
	var mu sync.Mutex
	var order []string
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/user", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		order = append(order, "PUT "+r.URL.Path)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true}`))
	})
	mux.HandleFunc("/sync/download/ovpn/", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		order = append(order, "GET "+r.URL.Path)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/x-openvpn-profile")
		_, _ = w.Write([]byte("client\nremote x 1194\n"))
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	seedTrafficNode(t, conn, 1, "node-a", srv)
	// Two users: alice (still active) and bob (disabled). Policy is pushed
	// for both, but only alice's profile lands in the ZIP.
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name, max_logins, is_active) VALUES (7, 'u7', 'alice', 3, 1), (8, 'u8', 'bob', 3, 0)`); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	out := DownloadAllOVPNClients(1, conn)
	if out == nil {
		t.Fatalf("DownloadAllOVPNClients = nil")
	}
	// ZIP must be readable and contain alice.ovpn.
	zr, err := zip.NewReader(bytes.NewReader(out), int64(len(out)))
	if err != nil {
		t.Fatalf("zip reader: %v", err)
	}
	names := []string{}
	for _, f := range zr.File {
		names = append(names, f.Name)
	}
	if len(names) != 1 || names[0] != "alice.ovpn" {
		t.Fatalf("zip contents = %v, want [alice.ovpn] only (disabled bob omitted)", names)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(order) < 2 {
		t.Fatalf("request order = %v, want policy PUT before download GET", order)
	}
	if !strings.HasPrefix(order[0], "PUT /sync/user") {
		t.Fatalf("first request = %q, want policy PUT /sync/user", order[0])
	}
	if !strings.HasPrefix(order[1], "GET /sync/download/ovpn/") {
		t.Fatalf("second request = %q, want profile GET", order[1])
	}
}
