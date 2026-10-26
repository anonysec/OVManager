package notify

import (
	"log"
	"strings"
	"testing"
)

func TestRunGuardedRecoversAndLogs(t *testing.T) {
	var buf strings.Builder
	prev := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(prev)

	runGuarded("notify worker", func() { panic("boom") })

	out := buf.String()
	if !strings.Contains(out, "notify worker") {
		t.Errorf("panic not attributed to the worker: %q", out)
	}
	if !strings.Contains(out, "boom") {
		t.Errorf("panic value not logged: %q", out)
	}
}

func TestRunGuardedRunsTheFunction(t *testing.T) {
	called := false
	runGuarded("notify worker", func() { called = true })
	if !called {
		t.Fatal("the guarded function did not run")
	}
}
