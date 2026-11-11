// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"crypto/tls"
	"net/http/httptest"
	"testing"
)

// The panel terminates TLS itself; a forwarded scheme is never trusted, and
// only a real TLS connection makes the base URL https.
func TestBaseURLUsesTheConnectionScheme(t *testing.T) {
	r := httptest.NewRequest("GET", "http://panel.example/sub/alice", nil)
	r.Header.Set("X-Forwarded-Proto", "https")
	if got := baseURL(r); got != "http://panel.example/" {
		t.Fatalf("plain HTTP base URL = %q, want http", got)
	}
	if externallySecure(r) {
		t.Fatal("a forwarded scheme must not mark the request secure")
	}

	r.TLS = &tls.ConnectionState{}
	if got := baseURL(r); got != "https://panel.example/" {
		t.Fatalf("TLS base URL = %q, want https", got)
	}
	if !externallySecure(r) {
		t.Fatal("TLS should mark the request secure")
	}
}
