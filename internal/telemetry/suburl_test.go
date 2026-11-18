// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func subURLDB(t *testing.T, prefix, domain string) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "sub.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	var p, d any
	if prefix != "" {
		p = prefix
	}
	if domain != "" {
		d = domain
	}
	_, err = conn.Exec(`
CREATE TABLE Setting (id INTEGER PRIMARY KEY, urlpath VARCHAR DEFAULT 'dashboard', subscription_url_prefix VARCHAR, subscription_path VARCHAR DEFAULT 'sub', panel_domain VARCHAR);
INSERT INTO Setting (id, urlpath, subscription_url_prefix, panel_domain) VALUES (1, 'dashboard', ?, ?);
`, p, d)
	if err != nil {
		t.Fatal(err)
	}
	return conn
}

func TestSubURLUsesConfiguredDomain(t *testing.T) {
	// A configured domain is the fallback: the old localhost fallback handed
	// every Telegram user a dead link, and the urlpath must not come back.
	got := subURL(subURLDB(t, "", "vpn.example.com"), "abc")
	want := "https://vpn.example.com/sub/abc.txt"
	if got != want {
		t.Fatalf("subURL = %q, want %q", got, want)
	}
}

func TestSubURLExplicitPrefixWins(t *testing.T) {
	got := subURL(subURLDB(t, "https://sub.example.com/", "vpn.example.com"), "abc")
	want := "https://sub.example.com/sub/abc.txt"
	if got != want {
		t.Fatalf("subURL = %q, want %q", got, want)
	}
}

func TestSubURLWithoutPrefixOrDomainIsEmpty(t *testing.T) {
	if got := subURL(subURLDB(t, "", ""), "abc"); got != "" {
		t.Fatalf("subURL = %q, want empty (no usable host)", got)
	}
}
