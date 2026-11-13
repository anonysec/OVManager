// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import "testing"

func TestRecentFromReturnsNewestFirst(t *testing.T) {
	lines := []map[string]any{
		{"id": float64(1), "ts": float64(10), "action": "A"},
		{"id": float64(2), "ts": float64(20), "action": "A"},
		{"id": float64(3), "ts": float64(30), "action": "A"},
	}
	got := recentFrom(lines, 2, nil, nil)
	if len(got) != 2 || got[0]["id"] != int64(3) || got[1]["id"] != int64(2) {
		t.Fatalf("got %v, want ids 3,2", got)
	}
}

func TestRecentFromFiltersBeforeLimit(t *testing.T) {
	lines := []map[string]any{
		{"id": float64(1), "actor": "a", "action": "X"},
		{"id": float64(2), "actor": "b", "action": "X"},
		{"id": float64(3), "actor": "a", "action": "X"},
	}
	actor := "a"
	got := recentFrom(lines, 1, &actor, nil)
	if len(got) != 1 || got[0]["id"] != int64(3) {
		t.Fatalf("got %v, want the newest actor=a line", got)
	}
}
