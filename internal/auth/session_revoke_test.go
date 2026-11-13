// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import "testing"

// Revoking a token must also drop its identity-cache entry; otherwise the
// next verification serves the cached identity for up to 30 seconds.
func TestRevokedTokenIsNotServedFromCache(t *testing.T) {
	svc := NewService(nil, t.TempDir())
	raw, err := svc.CreateSession("owner", "owner", "test", "127.0.0.1", 60)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := svc.VerifySession(raw); !ok {
		t.Fatal("fresh token did not verify")
	}
	if !svc.RevokeToken(raw) {
		t.Fatal("RevokeToken did not find the session")
	}
	if _, ok := svc.VerifySession(raw); ok {
		t.Fatal("revoked token still verifies from the identity cache")
	}
}
