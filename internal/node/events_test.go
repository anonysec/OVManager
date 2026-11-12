// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"bufio"
	"context"
	"encoding/pem"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func hostPort(t *testing.T, raw string) (string, int) {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatal(err)
	}
	return u.Hostname(), port
}

func pinnedClient(t *testing.T, srv *httptest.Server) *Client {
	t.Helper()
	host, port := hostPort(t, srv.URL)
	pin := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
	c, err := NewClient(host, port, "api-key", pin, "", 0)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// sseServer is a fake node: status for GET /sync/events, else writes frames
// and holds the stream open until the panel hangs up.
func sseServer(t *testing.T, status int, frames func(w http.ResponseWriter)) (*httptest.Server, *atomic.Int64) {
	t.Helper()
	var hits atomic.Int64
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.URL.Path != "/sync/events" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		if status != http.StatusOK {
			w.WriteHeader(status)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		frames(w)
		<-r.Context().Done()
	}))
	t.Cleanup(func() {
		srv.CloseClientConnections()
		srv.Close()
	})
	return srv, &hits
}

func TestStreamEventsParsesFrames(t *testing.T) {
	srv, _ := sseServer(t, http.StatusOK, func(w http.ResponseWriter) {
		fl := w.(http.Flusher)
		write := func(s string) {
			_, _ = fmt.Fprint(w, s)
			fl.Flush()
		}
		write("event: snapshot\ndata: {\"revision\":0,\"data\":{\"live_count\":2}}\n\n")
		write(": ping\n\n") // keepalive comment: never reaches on
		write("event: sessions\ndata: {\"revision\":3,\"data\":{\"live_count\":3}}\n\n")
		// Multi-line data joins with a newline inside one frame.
		write("event: usage\ndata: {\"revision\":4,\"data\":\ndata: {\"totals\":{\"2\":480}}}\n\n")
	})
	c := pinnedClient(t, srv)

	stop := errors.New("collected enough")
	var got []NodeEvent
	err := c.StreamEvents(context.Background(), func(ev NodeEvent) error {
		got = append(got, ev)
		if len(got) == 3 {
			return stop
		}
		return nil
	})
	if !errors.Is(err, stop) {
		t.Fatalf("StreamEvents err = %v, want the collector stop", err)
	}
	want := []struct {
		kind     string
		revision int64
		body     string
	}{
		{"snapshot", 0, `{"live_count":2}`},
		{"sessions", 3, `{"live_count":3}`},
		{"usage", 4, `{"totals":{"2":480}}`},
	}
	if len(got) != len(want) {
		t.Fatalf("got %d frames, want %d: %+v", len(got), len(want), got)
	}
	for i, w := range want {
		if got[i].Kind != w.kind {
			t.Errorf("frame %d kind %q, want %q", i, got[i].Kind, w.kind)
		}
		if got[i].Revision != w.revision {
			t.Errorf("frame %d revision %d, want %d", i, got[i].Revision, w.revision)
		}
		if strings.TrimSpace(string(got[i].Data)) != w.body {
			t.Errorf("frame %d data %s, want %s", i, got[i].Data, w.body)
		}
	}
}

func TestStreamEventsNotFoundSentinel(t *testing.T) {
	for _, status := range []int{http.StatusNotFound, http.StatusMethodNotAllowed} {
		srv, hits := sseServer(t, status, func(w http.ResponseWriter) { t.Error("no frames expected") })
		c := pinnedClient(t, srv)
		err := c.StreamEvents(context.Background(), func(NodeEvent) error { return nil })
		if !errors.Is(err, ErrNoEvents) {
			t.Fatalf("status %d: err = %v, want ErrNoEvents", status, err)
		}
		if hits.Load() != 1 {
			t.Fatalf("status %d: %d requests, want exactly one (no in-client retry)", status, hits.Load())
		}
	}
}

func TestStreamEventsFrameSizeCap(t *testing.T) {
	srv, _ := sseServer(t, http.StatusOK, func(w http.ResponseWriter) {
		fl := w.(http.Flusher)
		_, _ = w.Write([]byte("event: sessions\ndata: {\"revision\":1,\"data\":\""))
		fl.Flush()
		_, _ = w.Write([]byte(strings.Repeat("x", 1<<20)))
		fl.Flush()
		_, _ = w.Write([]byte("\"}\n\n"))
		fl.Flush()
	})
	c := pinnedClient(t, srv)
	err := c.StreamEvents(context.Background(), func(NodeEvent) error { return nil })
	if err == nil {
		t.Fatal("an oversized frame was accepted")
	}
	if !errors.Is(err, bufio.ErrTooLong) {
		t.Fatalf("err = %v, want the scanner length cap", err)
	}
}

func TestStreamEventsHonorsContext(t *testing.T) {
	srv, _ := sseServer(t, http.StatusOK, func(w http.ResponseWriter) {
		fl := w.(http.Flusher)
		_, _ = w.Write([]byte("event: snapshot\ndata: {\"revision\":0,\"data\":{}}\n\n"))
		fl.Flush()
		// Then hold the stream open: the panel must leave on ctx cancel.
	})
	c := pinnedClient(t, srv)

	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	start := time.Now()
	err := c.StreamEvents(ctx, func(NodeEvent) error { return nil })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want the context deadline", err)
	}
	if elapsed := time.Since(start); elapsed > 3*time.Second {
		t.Fatalf("StreamEvents took %s after cancel", elapsed)
	}
}

func TestStreamEventsRejectsWrongContentType(t *testing.T) {
	var hits atomic.Int64
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true}`))
	}))
	t.Cleanup(func() { srv.CloseClientConnections(); srv.Close() })
	c := pinnedClient(t, srv)
	err := c.StreamEvents(context.Background(), func(NodeEvent) error { return nil })
	if err == nil || strings.Contains(err.Error(), "ErrNoEvents") {
		t.Fatalf("err = %v, want a content-type failure", err)
	}
}
