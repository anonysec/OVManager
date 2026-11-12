// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package cli

import (
	"strings"
	"testing"
	"time"
)

func TestFetchHealthAnyPrefersAVersionedResponse(t *testing.T) {
	old := FetchHealth
	defer func() { FetchHealth = old }()
	FetchHealth = func(url string, _ time.Duration, _ string) (bool, string) {
		if strings.Contains(url, "public") {
			return true, ""
		}
		return true, "2.0.3"
	}
	ok, version := fetchHealthAny([]string{"https://public/health", "https://127.0.0.1/health"}, time.Second, "")
	if !ok || version != "2.0.3" {
		t.Fatalf("ok=%v version=%q, want the loopback version", ok, version)
	}
}

func TestFetchHealthAnyFallsBackToReachable(t *testing.T) {
	old := FetchHealth
	defer func() { FetchHealth = old }()
	FetchHealth = func(string, time.Duration, string) (bool, string) { return true, "" }
	ok, version := fetchHealthAny([]string{"https://public/health"}, time.Second, "")
	if !ok || version != "" {
		t.Fatalf("ok=%v version=%q", ok, version)
	}
}
