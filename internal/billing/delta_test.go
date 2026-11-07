package billing

import "testing"

// TestComputeTotalDelta pins the D5 rules: increases bill, unexplained
// decreases hold the baseline, explicit resets seed without billing.
func TestComputeTotalDelta(t *testing.T) {
	cases := []struct {
		name          string
		current       int64
		previous      int64
		explicitReset bool
		delta         int64
		baseline      int64
	}{
		{"increase", 120, 100, false, 20, 120},
		{"equal", 100, 100, false, 0, 100},
		{"decrease holds baseline", 100, 120, false, 0, 120},
		{"rebound to held baseline", 120, 120, false, 0, 120},
		{"rebound past held baseline", 130, 120, false, 10, 130},
		{"explicit reset seeds", 500, 100, true, 0, 500},
		{"explicit reset to zero", 0, 100, true, 0, 0},
		{"above 2^53 one byte", 9007199254740993, 9007199254740992, false, 1, 9007199254740993},
		{"max int64 increase", 9223372036854775807, 9223372036854775806, false, 1, 9223372036854775807},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			delta, baseline := ComputeTotalDelta(c.current, c.previous, c.explicitReset)
			if delta != c.delta || baseline != c.baseline {
				t.Fatalf("ComputeTotalDelta(%d,%d,%v) = (%d,%d), want (%d,%d)",
					c.current, c.previous, c.explicitReset, delta, baseline, c.delta, c.baseline)
			}
		})
	}
}
