package node

import "testing"

func TestNodeVersionCompatLaneD(t *testing.T) {
	cases := []struct {
		agent string
		want  string
	}{
		{"1.3.0", "compatible"},
		{"0.9", "incompatible"},
	}
	for _, c := range cases {
		got := nodeVersionCompat(c.agent)["verdict"]
		if got != c.want {
			t.Errorf("agent %s: verdict = %v, want %s", c.agent, got, c.want)
		}
	}
}
