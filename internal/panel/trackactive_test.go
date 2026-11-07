package panel

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestTrackActiveSkipsRestore: the restore handler drains in-flight
// requests; counting itself would self-deadlock into the 10s timeout.
func TestTrackActiveSkipsRestore(t *testing.T) {
	h, _ := newBackupTestHandler(t)
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })
	wrapped := h.TrackActive(next)
	done := make(chan struct{})
	go func() {
		wrapped.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodPost, "/api/maintenance/backup/restore", nil))
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("restore request was tracked and blocked")
	}
}
