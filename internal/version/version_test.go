// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package version_test

import (
	"testing"

	"github.com/anonysec/OVManager/internal/version"
)

func TestIsLegacyPreReset(t *testing.T) {
	tests := []struct {
		v    string
		want bool
	}{
		{"2.0.0", false},
		{"v2.0.0", false},
		{"2.0.1", false},
		{"v2.0.1-rc1", false},
		{"2.4.6", true},
		{"v2.4.6", true},
		{"2.1.0", true},
		{"v2.3.0", true},
		{"1.4.24", false},
	}

	for _, tt := range tests {
		got := version.IsLegacyPreReset(tt.v)
		if got != tt.want {
			t.Errorf("IsLegacyPreReset(%q) = %v; want %v", tt.v, got, tt.want)
		}
	}
}
