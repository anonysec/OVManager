// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"testing"
)

func TestFilterUserCNHandlesNumericAndNodeSuffixedNames(t *testing.T) {
	list := []map[string]any{
		{"common_name": "42"},
		{"common_name": "42-nodeA"},
		{"common_name": "alice"},
		{"common_name": "alice-nodeA"},
		{"common_name": "43-nodeA"},
		{"common_name": "alice-nodeB"},
	}
	names := map[string]string{"42": "alice"}
	known := map[string]bool{"alice": true}
	got := filterUserCN(list, "alice", "nodeA", names, known)
	if len(got) != 4 {
		t.Fatalf("filtered session count = %d, want 4: %v", len(got), got)
	}
}

func TestUserAuthErrorCountResolvesNumericAndSuffixedCommonNames(t *testing.T) {
	got := userAuthErrorCount(map[string]any{
		"42-nodeA":    float64(2),
		"alice-nodeA": float64(3),
		"43-nodeA":    float64(5),
	}, "alice", "nodeA", map[string]string{"42": "alice"}, map[string]bool{"alice": true})
	if got != 5 {
		t.Fatalf("user auth errors = %d, want 5 for numeric and username keys", got)
	}
}

func TestPerUserSessionAndAuthResolutionPrefersNumericUsernameOverCollidingID(t *testing.T) {
	// User alice has ID 42 while another panel user is literally named "42".
	// Exact and node-suffixed numeric usernames must not be remapped to alice.
	names := map[string]string{"42": "alice", "99": "42"}
	known := map[string]bool{"alice": true, "42": true}
	sessions := []map[string]any{
		{"common_name": "42"},
		{"common_name": "42-nodeA"},
	}
	authErrors := map[string]any{"42": float64(2), "42-nodeA": float64(6)}

	if got := len(filterUserCN(sessions, "42", "nodeA", names, known)); got != 2 {
		t.Errorf("numeric-name user sessions = %d, want both numeric common-name forms", got)
	}
	if got := len(filterUserCN(sessions, "alice", "nodeA", names, known)); got != 0 {
		t.Errorf("alice sessions = %d, want no sessions reassigned from username 42", got)
	}
	if got := userAuthErrorCount(authErrors, "42", "nodeA", names, known); got != 8 {
		t.Errorf("numeric-name user auth events = %d, want 8", got)
	}
	if got := userAuthErrorCount(authErrors, "alice", "nodeA", names, known); got != 0 {
		t.Errorf("alice auth events = %d, want no events reassigned from username 42", got)
	}
}

func TestDiagnosticNodeResultRetainsNodeWhenFanoutFails(t *testing.T) {
	name, data := diagnosticNodeResult(FanoutDeadline{Msg: "deadline"}, "nodeA")
	if name != "nodeA" || data != nil {
		t.Fatalf("timeout result = (%q, %v), want configured node and no data", name, data)
	}
}

func TestDiagnosticNodeResultUsesReturnedNodeAndData(t *testing.T) {
	wantData := map[string]any{"live_sessions": []any{}}
	name, data := diagnosticNodeResult([]any{"nodeA", wantData}, "fallback")
	if name != "nodeA" || data["live_sessions"] == nil {
		t.Fatalf("result = (%q, %v), want returned node and data", name, data)
	}
}

func TestUserHealthRowUsesDiagnosticsSnapshot(t *testing.T) {
	u := diagUser{id: 42, name: "alice", isActive: true, maxLogins: 2}
	got := userHealthRow(u, map[string]any{"totals": map[string]any{
		"live_count": 2, "stale_marker_count": 1, "user_auth_errors": 4,
	}})
	if got["active_connections"] != 2 || got["stale_markers"] != 1 || got["auth_events"] != 4 || got["status"] != "stale" {
		t.Fatalf("health row = %v, want active=2 stale=1 auth=4 status=stale", got)
	}
}

func TestResolvedSessionUsernameHandlesNodeSuffixes(t *testing.T) {
	names := map[string]string{"42": "alice"}
	known := map[string]bool{"alice": true}
	for _, tc := range []struct {
		commonName string
		want       string
	}{
		{commonName: "42", want: "alice"},
		{commonName: "42-nodeA", want: "alice"},
		{commonName: "alice-nodeA", want: "alice"},
	} {
		if got := resolved(names, tc.commonName, "nodeA", known); got != tc.want {
			t.Errorf("resolved(%q) = %q, want %q", tc.commonName, got, tc.want)
		}
	}
}

func TestResolvedSessionUsernamePrefersNumericUsernameOverCollidingID(t *testing.T) {
	names := map[string]string{"42": "alice", "99": "42"}
	known := map[string]bool{"alice": true, "42": true}
	for _, commonName := range []string{"42", "42-nodeA"} {
		if got := resolved(names, commonName, "nodeA", known); got != "42" {
			t.Errorf("resolved(%q) = %q, want the known numeric username", commonName, got)
		}
	}
}
