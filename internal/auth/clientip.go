// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"github.com/anonysec/OVManager/go/internal/config"
	"net"
	"net/http"
	"strings"
	"sync"
)

var (
	// TrustedHeader specifies an explicit header to trust behind a trusted proxy
	// (e.g. "CF-Connecting-IP", "X-Real-IP", or "X-Forwarded-For").
	TrustedHeader = config.EnvOrFile("TRUSTED_PROXY_HEADER", "")

	cidrMu       sync.RWMutex
	trustedCIDRs []*net.IPNet
)

func init() {
	initTrustedCIDRs()
}

func defaultTrustedCIDRStrings() []string {
	return []string{
		"127.0.0.0/8",    // IPv4 loopback
		"::1/128",        // IPv6 loopback
		"10.0.0.0/8",     // RFC1918
		"172.16.0.0/12",  // RFC1918
		"192.168.0.0/16", // RFC1918
		"fc00::/7",       // IPv6 Unique Local Address
	}
}

func initTrustedCIDRs() {
	raw := strings.TrimSpace(config.EnvOrFile("TRUSTED_PROXY_CIDRS", ""))
	if raw == "" {
		raw = strings.TrimSpace(config.EnvOrFile("TRUSTED_PROXIES", ""))
	}
	var cidrList []string
	if raw != "" {
		for _, part := range strings.Split(raw, ",") {
			part = strings.TrimSpace(part)
			if part != "" {
				if !strings.Contains(part, "/") {
					if strings.Contains(part, ":") {
						part += "/128"
					} else {
						part += "/32"
					}
				}
				cidrList = append(cidrList, part)
			}
		}
	} else {
		cidrList = defaultTrustedCIDRStrings()
	}

	var parsed []*net.IPNet
	for _, s := range cidrList {
		if _, ipNet, err := net.ParseCIDR(s); err == nil {
			parsed = append(parsed, ipNet)
		}
	}
	cidrMu.Lock()
	trustedCIDRs = parsed
	cidrMu.Unlock()
}

// SetTrustedCIDRs overrides the trusted proxy CIDR allowlist.
func SetTrustedCIDRs(cidrs ...string) {
	var parsed []*net.IPNet
	for _, s := range cidrs {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		if !strings.Contains(s, "/") {
			if strings.Contains(s, ":") {
				s += "/128"
			} else {
				s += "/32"
			}
		}
		if _, ipNet, err := net.ParseCIDR(s); err == nil {
			parsed = append(parsed, ipNet)
		}
	}
	cidrMu.Lock()
	trustedCIDRs = parsed
	cidrMu.Unlock()
}

func isTrustedProxyIP(remoteHost string) bool {
	ip := net.ParseIP(remoteHost)
	if ip == nil {
		return false
	}
	cidrMu.RLock()
	defer cidrMu.RUnlock()
	for _, ipNet := range trustedCIDRs {
		if ipNet.Contains(ip) {
			return true
		}
	}
	return false
}

// ClientIP returns the verified client IP address. Forwarded headers are
// strictly accepted only when trustedProxy is true AND RemoteAddr originates
// from a verified trusted proxy CIDR.
func ClientIP(trustedProxy bool, r *http.Request) string {
	remoteHost, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		remoteHost = r.RemoteAddr
	}

	if !trustedProxy || !isTrustedProxyIP(remoteHost) {
		return remoteHost
	}

	headerToUse := strings.TrimSpace(TrustedHeader)
	if headerToUse == "" {
		headerToUse = strings.TrimSpace(config.EnvOrFile("TRUSTED_PROXY_HEADER", ""))
	}

	if headerToUse != "" {
		val := strings.TrimSpace(r.Header.Get(headerToUse))
		if val != "" {
			if headerToUse == "X-Forwarded-For" {
				parts := strings.Split(val, ",")
				candidate := strings.TrimSpace(parts[len(parts)-1])
				if net.ParseIP(candidate) != nil {
					return candidate
				}
			} else if net.ParseIP(val) != nil {
				return val
			}
		}
		return remoteHost
	}

	// Default fallback chain behind trusted proxy
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		candidate := strings.TrimSpace(parts[len(parts)-1])
		if net.ParseIP(candidate) != nil {
			return candidate
		}
	}
	if xri := strings.TrimSpace(r.Header.Get("X-Real-IP")); xri != "" {
		if net.ParseIP(xri) != nil {
			return xri
		}
	}
	if cf := strings.TrimSpace(r.Header.Get("CF-Connecting-IP")); cf != "" {
		if net.ParseIP(cf) != nil {
			return cf
		}
	}

	return remoteHost
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
