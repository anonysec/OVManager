// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"net"
	"net/http"
	"strings"
)

// ClientIP is the address of the peer that connected to the panel.
//
// The panel terminates TLS itself, so there is no forwarded-header trust
// question to answer: RemoteAddr is the client. Anything that reads
// X-Forwarded-For here would let the first hop choose its own rate-limit
// bucket.
func ClientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// BucketIP returns the rate-limiting key for an IP address.
// IPv4 addresses return verbatim. IPv6 addresses are bucketed into their
// /64 routing prefix to mitigate rotation bypass.
func BucketIP(ipStr string) string {
	ip := net.ParseIP(strings.TrimSpace(ipStr))
	if ip == nil {
		return ipStr
	}
	if ip.To4() != nil {
		return ip.String()
	}
	mask := net.CIDRMask(64, 128)
	return ip.Mask(mask).String() + "/64"
}
