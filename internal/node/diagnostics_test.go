// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"testing"
)

func TestDiagnosticNodeResultRetainsNodeWhenFanoutFails(t *testing.T) {
	name, data := diagnosticNodeResult(FanoutDeadline{Msg: "deadline"}, "nodeA")
	if name != "nodeA" || data != nil {
		t.Fatalf("timeout result = (%q, %v), want configured node and no data", name, data)
	}
}

func TestDiagnosticNodeResultUsesReturnedNodeAndData(t *testing.T) {
	wantData := &SessionsResponse{LiveSessions: []SessionEntry{{CommonName: "42"}}}
	name, data := diagnosticNodeResult([]any{"nodeA", wantData}, "fallback")
	if name != "nodeA" || data == nil || len(data.LiveSessions) != 1 {
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
