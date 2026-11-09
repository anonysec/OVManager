// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"testing"
)

func TestPurgeExpiredPrunesMemoryBuckets(t *testing.T) {
	d := setupAuthTestDB(t)
	svc := NewService(d, t.TempDir())
	now := nowSecs()
	svc.mu.Lock()
	svc.attempts["expired"] = []float64{now - float64(lockoutSeconds) - 10}
	svc.attempts["fresh"] = []float64{now - 10}
	svc.mu.Unlock()
	_ = svc.PurgeExpired()
	if n := svc.bucketCount("expired"); n != 0 {
		t.Fatalf("expired bucket still has %d entries, want 0", n)
	}
	if n := svc.bucketCount("fresh"); n != 1 {
		t.Fatalf("fresh bucket has %d entries, want 1", n)
	}
}
