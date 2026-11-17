// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import "testing"

func TestIdleExpiredSessionIsNotServedFromCache(t *testing.T) {
	svc := NewService(nil, t.TempDir())
	svc.IdleSeconds = 1
	raw, err := svc.CreateSession("owner", "owner", "test", "127.0.0.1", 60)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := svc.VerifySession(raw); !ok {
		t.Fatal("fresh token did not verify")
	}
	th := tokenHash(raw)
	svc.sessMu.Lock()
	entry := svc.sessions[th]
	entry.lastSeen = nowSecs() - 5
	svc.sessions[th] = entry
	svc.sessMu.Unlock()
	if _, ok := svc.VerifySession(raw); ok {
		t.Fatal("idle-expired token still verifies from the identity cache")
	}
}
