package telemetry

import "testing"

// TestBankerRoundMatches locks the banker's-rounding used in threshold
// titles against round() (golden values from billing_golden.json).
func TestBankerRoundMatches(t *testing.T) {
	cases := map[float64]int{0.5: 0, 1.5: 2, 2.5: 2, 79.5: 80, 80.5: 80, 84.5: 84, 85.5: 86, 99.5: 100, 100.0: 100, 33.33: 33}
	for in, want := range cases {
		if got := bankerRound(in); got != want {
			t.Errorf("bankerRound(%v) = %d, want %d", in, got, want)
		}
	}
}

// TestFormatEventFraming checks the exact SSE bytes (separators, key order).
func TestFormatEventFraming(t *testing.T) {
	got := formatEvent("users", 1759123456.5, []KV{{Key: "op", Val: "sync"}})
	want := "event: users\ndata: {\"op\": \"sync\", \"ts\": 1759123456.5}\n\n"
	if got != want {
		t.Fatalf("frame = %q, want %q", got, want)
	}
}
