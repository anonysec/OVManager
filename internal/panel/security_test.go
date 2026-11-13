package panel

import (
	"testing"
	"time"
)

func TestLegacySecurityLogParsing(t *testing.T) {
	line := "Oct 30 12:34:56 REJECT CN=alice limit=2 active_files=3 msg=maximum sessions"
	event := parseLogLine(line, "", time.UTC)
	for key, want := range map[string]any{
		"common_name": "alice", "limit": "2", "active": "3",
		"reason": "maximum sessions", "action": "max_logins", "severity": "policy",
	} {
		if event[key] != want {
			t.Errorf("%s = %v, want %v", key, event[key], want)
		}
	}
	if event["ts"] == float64(0) || event["time_local"] == nil {
		t.Errorf("timestamp was not parsed: %v", event)
	}
}

func TestOngoingUsersSkipsDeviceLimit(t *testing.T) {
	events := []map[string]any{
		{"user": "alice", "ongoing": true, "action": "max_logins"},
		{"user": "bob", "ongoing": true, "action": "takeover_failed"},
		{"user": "carol", "ongoing": false, "action": "disabled"},
	}
	got := ongoingUsers(events)
	if len(got) != 1 || got[0] != "bob" {
		t.Fatalf("ongoing users = %v, want [bob]", got)
	}
}
