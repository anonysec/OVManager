// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import "testing"

// An unreachable node must not look like a reachable node with zero
// counters.
//
// dataOf used to return an empty map for a failed call, so every
// "data == nil" check downstream was dead code: the panel reported an
// unreachable node as reachable, with zero sessions and zero rejects.
func TestDataOfReportsAnUnreachableNode(t *testing.T) {
	if got := dataOf(nil); got != nil {
		t.Errorf("dataOf(nil) = %v, want nil so callers can tell unreachable from empty", got)
	}
}

// A node that answered must not look unreachable, even when the payload
// carries no data object.
func TestDataOfReportsAnAnsweredNode(t *testing.T) {
	got := dataOf(map[string]any{"success": true, "msg": "ok", "data": nil})
	if got == nil {
		t.Error("dataOf of an answered call = nil, want an empty map")
	}
	if len(got) != 0 {
		t.Errorf("dataOf = %v, want an empty map", got)
	}
	got = dataOf(map[string]any{"success": true, "data": map[string]any{"totals": map[string]any{"a": 1}}})
	if got == nil || got["totals"] == nil {
		t.Errorf("dataOf = %v, want the data object", got)
	}
}
