// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"fmt"
	"testing"
)

func TestSubEnforceCapEvictsOldestBuckets(t *testing.T) {
	subMu.Lock()
	defer subMu.Unlock()
	oldAttempts, oldCleanup := subAttempts, subLastCleanup
	defer func() {
		subAttempts = oldAttempts
		subLastCleanup = oldCleanup
	}()

	subAttempts = make(map[string][]float64, subMaxBuckets+3)
	for i := 0; i < subMaxBuckets+3; i++ {
		subAttempts[fmt.Sprintf("ip-%d", i)] = []float64{float64(i)}
	}

	subEnforceCap()

	if len(subAttempts) != subMaxBuckets {
		t.Fatalf("bucket count = %d, want %d", len(subAttempts), subMaxBuckets)
	}
	for i := 0; i < 3; i++ {
		if _, ok := subAttempts[fmt.Sprintf("ip-%d", i)]; ok {
			t.Errorf("oldest bucket ip-%d was retained", i)
		}
	}
	if _, ok := subAttempts["ip-3"]; !ok {
		t.Error("newest bucket expected to be retained")
	}
}
