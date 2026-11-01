// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"testing"
	"time"
)

// TestMetricsDue: the first call runs, a call inside the window is skipped,
// a call at the window edge runs.
func TestMetricsDue(t *testing.T) {
	metricsLastTS = time.Time{}
	t.Cleanup(func() { metricsLastTS = time.Time{} })
	base := time.Unix(1_700_000_000, 0)

	if !metricsDue(base) {
		t.Fatal("first call must run")
	}
	if metricsDue(base.Add(time.Minute)) {
		t.Fatal("a call inside the window must be skipped")
	}
	if !metricsDue(base.Add(metricsEvery())) {
		t.Fatal("a call at the window edge must run")
	}
}
