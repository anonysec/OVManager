// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
)

func TestURLPathCacheNoticesExternalDBChange(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DataDir", dir)
	live := filepath.Join(dir, "app.db")
	conn, err := db.Open(live)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`UPDATE Setting SET urlpath = 'alpha'`); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Svc: auth.NewService(conn, dir)}
	if got := h.URLPath(); got != "alpha" {
		t.Fatalf("URLPath = %q, want alpha", got)
	}
	if _, err := conn.Exec(`UPDATE Setting SET urlpath = 'beta'`); err != nil {
		t.Fatal(err)
	}
	if got := h.URLPath(); got != "beta" {
		t.Fatalf("URLPath after external change = %q, want beta", got)
	}
}

func TestURLPathCacheCanBeInvalidated(t *testing.T) {
	dir := t.TempDir()
	conn, err := db.Open(filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close() }()
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Svc: auth.NewService(conn, dir)}

	if _, err := conn.Exec(`UPDATE Setting SET urlpath = 'alpha'`); err != nil {
		t.Fatal(err)
	}
	if got := h.URLPath(); got != "alpha" {
		t.Fatalf("URLPath = %q, want alpha", got)
	}
	if _, err := conn.Exec(`UPDATE Setting SET urlpath = 'beta'`); err != nil {
		t.Fatal(err)
	}
	h.invalidateURLPath()
	if got := h.URLPath(); got != "beta" {
		t.Fatalf("URLPath after invalidation = %q, want beta", got)
	}
}
