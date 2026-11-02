// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"net/http"
	"testing"
)

func TestClientIP(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	req.RemoteAddr = "192.168.1.1:12345"
	req.Header.Set("X-Forwarded-For", "127.0.0.1, 203.0.113.195")

	// Untrusted proxy ignores headers and uses RemoteAddr host.
	if got := ClientIP(false, req); got != "192.168.1.1" {
		t.Errorf("ClientIP(false) = %q, want %q", got, "192.168.1.1")
	}

	// Trusted proxy takes the rightmost IP in XFF.
	if got := ClientIP(true, req); got != "203.0.113.195" {
		t.Errorf("ClientIP(true) = %q, want %q", got, "203.0.113.195")
	}

	// X-Real-IP takes precedence over X-Forwarded-For behind trusted proxy.
	req.Header.Set("X-Real-IP", "198.51.100.22")
	if got := ClientIP(true, req); got != "198.51.100.22" {
		t.Errorf("ClientIP(true, X-Real-IP) = %q, want %q", got, "198.51.100.22")
	}

	// CF-Connecting-IP takes highest precedence behind trusted proxy.
	req.Header.Set("CF-Connecting-IP", "203.0.113.88")
	if got := ClientIP(true, req); got != "203.0.113.88" {
		t.Errorf("ClientIP(true, CF-Connecting-IP) = %q, want %q", got, "203.0.113.88")
	}

	// Missing all proxy headers falls back to RemoteAddr host.
	req.Header.Del("CF-Connecting-IP")
	req.Header.Del("X-Real-IP")
	req.Header.Del("X-Forwarded-For")
	if got := ClientIP(true, req); got != "192.168.1.1" {
		t.Errorf("ClientIP(true, empty headers) = %q, want %q", got, "192.168.1.1")
	}
}
