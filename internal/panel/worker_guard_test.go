package panel

import (
	"log"
	"os"
	"strings"
	"testing"
)

// A panic in one worker tick must not stop the worker for the life of the
// process: the traffic worker is the only thing that counts bytes, and the
// only symptom of a dead worker is a log line that stops appearing.
func TestRunGuardedRecoversAndLogs(t *testing.T) {
	var buf strings.Builder
	prev := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(prev)

	runGuarded("traffic worker", func() { panic("boom") })

	out := buf.String()
	if !strings.Contains(out, "traffic worker") {
		t.Errorf("panic not attributed to the worker: %q", out)
	}
	if !strings.Contains(out, "boom") {
		t.Errorf("panic value not logged: %q", out)
	}
}

func TestRunGuardedRunsTheFunction(t *testing.T) {
	called := false
	runGuarded("traffic worker", func() { called = true })
	if !called {
		t.Fatal("the guarded function did not run")
	}
}

// The stack matters: a panic in a background goroutine has no other trace.
func TestRunGuardedLogsAStack(t *testing.T) {
	var buf strings.Builder
	prev := log.Writer()
	log.SetOutput(&buf)
	defer log.SetOutput(prev)

	runGuarded("traffic worker", func() { panic("boom") })

	if !strings.Contains(buf.String(), "goroutine") {
		t.Errorf("no stack in the log: %q", buf.String())
	}
	_ = os.Getpid
}
