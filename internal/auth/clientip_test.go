// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"net/http"
	"testing"
)

func TestClientIPSecurityAndCIDRTrust(t *testing.T) {
	// 1. Untrusted proxy ignores headers
	req, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	req.RemoteAddr = "127.0.0.1:12345"
	req.Header.Set("X-Forwarded-For", "203.0.113.195")
	if got := ClientIP(false, req); got != "127.0.0.1" {
		t.Errorf("ClientIP(false) = %q, want %q", got, "127.0.0.1")
	}

	// 2. RemoteAddr from an UNTRUSTED public IP must ignore proxy headers even when trustedProxy=true!
	reqPublic, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	reqPublic.RemoteAddr = "198.51.100.99:12345" // public IP directly accessing panel
	reqPublic.Header.Set("CF-Connecting-IP", "1.1.1.1")
	reqPublic.Header.Set("X-Forwarded-For", "2.2.2.2")
	if got := ClientIP(true, reqPublic); got != "198.51.100.99" {
		t.Fatalf("SECURITY FLAW: ClientIP trusted proxy headers from untrusted RemoteAddr %q, got %q", reqPublic.RemoteAddr, got)
	}

	// 3. RemoteAddr from a TRUSTED CIDR (e.g. 127.0.0.1 or 10.0.0.1) accepts forwarded header
	reqTrusted, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	reqTrusted.RemoteAddr = "127.0.0.1:54321"
	reqTrusted.Header.Set("X-Forwarded-For", "198.51.100.1, 203.0.113.195")
	if got := ClientIP(true, reqTrusted); got != "203.0.113.195" {
		t.Errorf("ClientIP from trusted proxy = %q, want %q", got, "203.0.113.195")
	}

	// 4. Configurable trusted header
	origHeader := TrustedHeader
	defer func() { TrustedHeader = origHeader }()
	TrustedHeader = "CF-Connecting-IP"

	reqCF, _ := http.NewRequest(http.MethodGet, "http://localhost/", nil)
	reqCF.RemoteAddr = "127.0.0.1:54321"
	reqCF.Header.Set("CF-Connecting-IP", "203.0.113.88")
	reqCF.Header.Set("X-Forwarded-For", "203.0.113.99")
	if got := ClientIP(true, reqCF); got != "203.0.113.88" {
		t.Errorf("ClientIP with TrustedHeader=CF-Connecting-IP = %q, want %q", got, "203.0.113.88")
	}
}

func TestBucketIP(t *testing.T) {
	// IPv4 returns full IP
	ipv4 := "203.0.113.195"
	if got := BucketIP(ipv4); got != ipv4 {
		t.Errorf("BucketIP(%s) = %q, want %q", ipv4, got, ipv4)
	}

	// IPv6 buckets by /64
	ip1 := "2001:db8:abcd:0012:0000:0000:0000:0001"
	ip2 := "2001:db8:abcd:0012:ffff:ffff:ffff:ffff"
	ipOtherSubnet := "2001:db8:abcd:0013:0000:0000:0000:0001"

	b1 := BucketIP(ip1)
	b2 := BucketIP(ip2)
	bOther := BucketIP(ipOtherSubnet)

	if b1 != b2 {
		t.Errorf("expected same /64 bucket for %s and %s, got %q and %q", ip1, ip2, b1, b2)
	}
	if b1 == bOther {
		t.Errorf("expected different /64 buckets, got same %q", b1)
	}
}
