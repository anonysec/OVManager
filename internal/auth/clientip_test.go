// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"net/http"
	"testing"
)

// The panel terminates TLS itself: the peer address is the client, and a
// forwarded header is never trusted.
func TestClientIPIsThePeer(t *testing.T) {
	req, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	req.RemoteAddr = "127.0.0.1:12345"
	req.Header.Set("X-Forwarded-For", "203.0.113.195")
	req.Header.Set("CF-Connecting-IP", "1.1.1.1")
	if got := ClientIP(req); got != "127.0.0.1" {
		t.Fatalf("ClientIP = %q, want the peer address", got)
	}

	bad, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	bad.RemoteAddr = "not-a-host-port"
	if got := ClientIP(bad); got != "not-a-host-port" {
		t.Fatalf("ClientIP without a port = %q", got)
	}
}

func TestBucketIP(t *testing.T) {
	ipv4 := "203.0.113.195"
	if got := BucketIP(ipv4); got != ipv4 {
		t.Errorf("BucketIP(%s) = %q", ipv4, got)
	}
	b1 := BucketIP("2001:db8:abcd:0012::1")
	b2 := BucketIP("2001:db8:abcd:0012:ffff::1")
	if b1 != b2 {
		t.Errorf("same /64 should share a bucket: %q %q", b1, b2)
	}
	if b1 == BucketIP("2001:db8:abcd:0013::1") {
		t.Error("different /64 must not share a bucket")
	}
}
