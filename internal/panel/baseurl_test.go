// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"crypto/tls"
	"net/http/httptest"
	"testing"
)

func TestBaseURLTrustsForwardedSchemeOnlyBehindConfiguredProxy(t *testing.T) {
	t.Setenv("OVM_APP_DIR", t.TempDir())
	t.Setenv("TRUSTED_PROXY", "false")

	r := httptest.NewRequest("GET", "http://panel.example/sub/alice", nil)
	r.Header.Set("X-Forwarded-Proto", "https")
	if got := baseURL(r); got != "http://panel.example/" {
		t.Fatalf("untrusted forwarded base URL = %q, want http", got)
	}
	if externallySecure(r) {
		t.Fatal("untrusted forwarded scheme must not mark the request secure")
	}

	r.TLS = &tls.ConnectionState{}
	if got := baseURL(r); got != "https://panel.example/" {
		t.Fatalf("direct TLS base URL = %q, want https", got)
	}
	r.TLS = nil

	t.Setenv("TRUSTED_PROXY", "true")
	if got := baseURL(r); got != "https://panel.example/" {
		t.Fatalf("trusted forwarded base URL = %q, want https", got)
	}
	if !externallySecure(r) {
		t.Fatal("trusted forwarded HTTPS should mark the request secure")
	}

	r.Header.Set("X-Forwarded-Proto", "https, http")
	if got := baseURL(r); got != "https://panel.example/" {
		t.Fatalf("first forwarded scheme base URL = %q, want https", got)
	}
}
