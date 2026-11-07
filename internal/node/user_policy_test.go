package node

import (
	"testing"
	"time"
)

func TestAccessBlockedBoundaries(t *testing.T) {
	now := time.Date(2026, 11, 6, 12, 0, 0, 0, time.UTC)
	i64 := func(v int64) *int64 { return &v }
	cases := []struct {
		name   string
		expiry string
		total  *int64
		used   int64
		want   string
	}{
		{"no quota no expiry", "", nil, 0, ""},
		{"no quota with usage", "", nil, 999, ""},
		{"expiry yesterday", "2026-11-05", nil, 0, "expired"},
		{"expiry today still allowed", "2026-11-06", nil, 0, ""},
		{"expiry tomorrow", "2026-11-07", nil, 0, ""},
		{"expiry with timestamp suffix", "2026-11-05T23:59:59Z", nil, 0, "expired"},
		{"exactly at quota", "", i64(100), 100, "out of traffic"},
		{"below quota", "", i64(100), 99, ""},
		{"over quota", "", i64(100), 101, "out of traffic"},
		{"zero quota no usage", "", i64(0), 0, "out of traffic"},
		{"expired beats quota", "2026-11-01", i64(100), 0, "expired"},
	}
	for _, tc := range cases {
		if got := AccessBlocked(tc.expiry, tc.total, tc.used, now); got != tc.want {
			t.Errorf("%s: AccessBlocked = %q, want %q", tc.name, got, tc.want)
		}
	}
}
