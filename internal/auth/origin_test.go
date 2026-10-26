// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"crypto/tls"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOriginRejectedUsesTheFullOriginTuple(t *testing.T) {
	tests := []struct {
		name         string
		trustedProxy bool
		host         string
		tls          bool
		forwarded    string
		origin       string
		wantReject   bool
	}{
		{name: "same-origin HTTP", host: "panel.example", origin: "http://panel.example"},
		{name: "same-origin HTTPS", host: "panel.example", tls: true, origin: "https://panel.example"},
		{name: "scheme downgrade on HTTPS", host: "panel.example", tls: true, origin: "http://panel.example", wantReject: true},
		{name: "scheme upgrade on HTTP", host: "panel.example", origin: "https://panel.example", wantReject: true},
		{name: "trusted HTTPS proxy", host: "panel.example", trustedProxy: true, forwarded: "https", origin: "https://panel.example"},
		{name: "trusted proxy rejects different scheme", host: "panel.example", trustedProxy: true, forwarded: "https", origin: "http://panel.example", wantReject: true},
		{name: "untrusted forwarded scheme is ignored", host: "panel.example", forwarded: "https", origin: "https://panel.example", wantReject: true},
		{name: "host mismatch", host: "panel.example", origin: "http://other.example", wantReject: true},
		{name: "port mismatch", host: "panel.example:8443", tls: true, origin: "https://panel.example:9443", wantReject: true},
		{name: "implicit HTTPS port matches explicit default", host: "panel.example:443", tls: true, origin: "https://panel.example"},
		{name: "invalid port rejected", host: "panel.example", origin: "http://panel.example:65536", wantReject: true},
		{name: "non-origin path rejected", host: "panel.example", origin: "http://panel.example/path", wantReject: true},
		{name: "userinfo rejected", host: "panel.example", origin: "http://attacker@panel.example", wantReject: true},
		{name: "null origin rejected", host: "panel.example", origin: "null", wantReject: true},
		{name: "empty fragment rejected", host: "panel.example", origin: "http://panel.example/#", wantReject: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			svc := &Service{TrustedProxy: tt.trustedProxy}
			r := httptest.NewRequest(http.MethodPost, "http://panel.example/api/settings", nil)
			r.Host = tt.host
			if tt.tls {
				r.TLS = &tls.ConnectionState{}
			}
			if tt.forwarded != "" {
				r.Header.Set("X-Forwarded-Proto", tt.forwarded)
			}
			r.Header.Set("Origin", tt.origin)

			if got := svc.originRejected(r); got != tt.wantReject {
				t.Errorf("originRejected() = %v, want %v", got, tt.wantReject)
			}
		})
	}
}

func TestOriginRejectedOnlyAllowsAnAbsentOrigin(t *testing.T) {
	svc := &Service{}
	newRequest := func() *http.Request {
		r := httptest.NewRequest(http.MethodPost, "http://panel.example/api/settings", nil)
		r.Host = "panel.example"
		return r
	}

	if got := svc.originRejected(newRequest()); got {
		t.Error("missing Origin should remain allowed for non-browser clients")
	}

	empty := newRequest()
	empty.Header.Add("Origin", "")
	if got := svc.originRejected(empty); !got {
		t.Error("explicitly empty Origin should be rejected, not treated as absent")
	}

	duplicate := newRequest()
	duplicate.Header.Add("Origin", "http://panel.example")
	duplicate.Header.Add("Origin", "http://attacker.example")
	if got := svc.originRejected(duplicate); !got {
		t.Error("multiple Origin values should be rejected as ambiguous")
	}
}
