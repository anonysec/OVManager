// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"net"
	"net/http"
	"strings"
)

// ClientIP returns the client IP address, honouring X-Forwarded-For only
// behind a trusted proxy. This is the single implementation shared by
// auth.Service and panel.Handler.
//
// ponytail: rightmost XFF entry only; add X-Real-IP/Forwarded when a second
// proxy hop shows up in the field.
func ClientIP(trustedProxy bool, r *http.Request) string {
	if trustedProxy {
		if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
			parts := strings.Split(xff, ",")
			if v := strings.TrimSpace(parts[len(parts)-1]); v != "" {
				return v
			}
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	return host
}
