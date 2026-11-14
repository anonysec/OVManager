// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

// The subscription page is a top-level route (like /api and /health), so the
// generated prefix must not inherit the panel's urlpath. Prefixing it with
// /dashboard produced links the SPA answered instead of the config page.
func TestSubscriptionPrefixStaysTopLevel(t *testing.T) {
	t.Setenv("PublicUrl", "")
	t.Setenv("SubscriptionPath", "")
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`UPDATE Setting SET urlpath = 'dashboard'`); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(auth.NewService(conn, t.TempDir()))

	req := httptest.NewRequest(http.MethodGet, "http://panel.example:2095/settings", nil)
	rec := httptest.NewRecorder()
	h.getSettings(rec, req)

	var body struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	got, _ := body.Data["subscription_url_prefix"].(string)
	if got != "http://panel.example:2095/" {
		t.Fatalf("subscription prefix = %q, want the top-level origin", got)
	}
}
