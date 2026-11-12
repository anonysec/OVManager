// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package acme

import "testing"

func TestCommonNameOmitsIPAddresses(t *testing.T) {
	if got := commonName([]string{"203.0.113.9"}); got != "" {
		t.Fatalf("IP common name = %q, want empty (IP belongs in the SAN)", got)
	}
	if got := commonName([]string{"panel.example"}); got != "panel.example" {
		t.Fatalf("DNS common name = %q", got)
	}
	if got := commonName(nil); got != "" {
		t.Fatalf("empty domains = %q", got)
	}
}
