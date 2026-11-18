// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

func TestSubscriptionUpdateFailureDoesNotClaimSuccess(t *testing.T) {
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Svc: auth.NewService(conn, dir)}
	if err := conn.Close(); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest("POST", "/api/settings/subscription", strings.NewReader(`{"subscription_path":"vpn"}`))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.updateSubscription(rec, req)
	if strings.Contains(rec.Body.String(), "updated") {
		t.Fatalf("failed update reported success: %s", rec.Body.String())
	}
}
