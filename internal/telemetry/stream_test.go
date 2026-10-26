package telemetry

import (
	"bufio"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestStreamReturnsWhenClientStopsReading(t *testing.T) {
	bus := NewBus()
	done := make(chan struct{})
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		StreamHandler(nil, bus)(w, r)
		close(done)
	})
	srv := httptest.NewServer(h)
	defer srv.Close()

	req, _ := http.NewRequest(http.MethodGet, srv.URL, nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("stream: %v", err)
	}
	rd := bufio.NewReader(resp.Body)
	// read ready frame
	ready := ""
	for {
		line, err := rd.ReadString('\n')
		if err != nil {
			t.Fatalf("read ready: %v", err)
		}
		ready += line
		if line == "\n" {
			break
		}
	}
	if !strings.HasPrefix(ready, "event: ready") {
		t.Fatalf("ready = %q", ready)
	}
	resp.Body.Close()

	bus.Publish("users", KV{Key: "op", Val: "sync"})

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("handler did not return after client stopped reading")
	}
}
