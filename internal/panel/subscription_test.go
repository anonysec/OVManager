// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

// The Settings page writes the subscription path to the database; routing
// must use it, not only the .env fallback.
func TestSubHandlerUsesSavedPath(t *testing.T) {
	t.Setenv("SubscriptionPath", "")
	conn, err := db.Open(filepath.Join(t.TempDir(), "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`UPDATE Setting SET subscription_path = 'vpn'`); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(auth.NewService(conn, t.TempDir()))

	req := httptest.NewRequest(http.MethodGet, "/vpn/static/subscription.js", nil)
	rec := httptest.NewRecorder()
	h.SubHandler().ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (saved subscription path not routed)", rec.Code)
	}
}
