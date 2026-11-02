// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"testing"
)

func TestVersionNewerRefusesPreReset(t *testing.T) {
	if versionNewer("2.4.6", "2.0.0") {
		t.Errorf("versionNewer(2.4.6, 2.0.0) = true; want false (legacy pre-reset line)")
	}
	if versionNewer("v2.4.6", "2.0.0") {
		t.Errorf("versionNewer(v2.4.6, 2.0.0) = true; want false (legacy pre-reset line)")
	}
	if versionNewer("2.1.0", "2.0.0") {
		t.Errorf("versionNewer(2.1.0, 2.0.0) = true; want false (legacy pre-reset line)")
	}
	if !versionNewer("2.0.1", "2.0.0") {
		t.Errorf("versionNewer(2.0.1, 2.0.0) = false; want true")
	}
}
