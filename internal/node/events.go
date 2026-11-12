// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// ErrNoEvents marks a node without /sync/events (pre-2.0.15 agent): the
// supervisor switches that node to permanent poll fallback and stops
// reconnecting.
var ErrNoEvents = errors.New("node does not stream events")

const (
	// eventHeaderTimeout bounds waiting for the response headers only; the
	// stream body itself is unbounded — it lives until it ends or ctx is
	// done. A client Timeout here would cut every healthy stream at N s.
	eventHeaderTimeout = 15 * time.Second
	// eventFrameCap bounds one SSE line. The node's largest frame is a
	// sessions snapshot (a few KiB); anything past this is a broken node,
	// not an invitation to buffer without limit.
	eventFrameCap = 1 << 20
)

// NodeEvent is one frame of the /sync/events stream. Revision is monotonic
// within one connection only; a fresh stream's snapshot (revision 0) is
// trusted unconditionally, so lost frames can never stick.
type NodeEvent struct {
	Kind     string // "snapshot" | "sessions" | "usage" | "heartbeat"
	Revision int64
	Data     json.RawMessage
}

// StreamEvents opens the node's event stream and calls on per frame until
// the stream ends or ctx is done. Exactly one dial: reconnect policy and
// backoff belong to the supervisor, not here. A node that answers 404/405
// returns ErrNoEvents so the caller can fall back to polling permanently.
func (c *Client) StreamEvents(ctx context.Context, on func(NodeEvent) error) error {
	// A private transport clone: ResponseHeaderTimeout bounds the header
	// wait without touching the shared RPC transport or the request
	// context, whose deadline would otherwise kill the stream at 15 s.
	tr := c.cachedTransport().Clone()
	tr.ResponseHeaderTimeout = eventHeaderTimeout
	hc := &http.Client{Transport: tr}
	resp, err := c.streamReq(ctx, "/sync/events", hc)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusNotFound, http.StatusMethodNotAllowed:
		return ErrNoEvents
	case http.StatusOK:
	default:
		return &nodeError{node: c.address, status: resp.StatusCode}
	}
	if ct := resp.Header.Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		return fmt.Errorf("node %s: /sync/events answered %q, not text/event-stream", c.address, ct)
	}
	if err := readEventStream(resp.Body, on); err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return err
	}
	return ctx.Err()
}

// streamReq is the request build and send for /sync/events; the path is a
// parameter with the literal "/sync/events" at the call site so the contract
// scanner ties the route to this function the same way it ties every other
// route to its request site.
func (c *Client) streamReq(ctx context.Context, path string, hc *http.Client) (*http.Response, error) {
	rawURL := c.scheme + "://" + c.address + path
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil) // #nosec // address comes from trusted node record
	if err != nil {
		return nil, err
	}
	for k, v := range c.headers {
		req.Header.Set(k, v)
	}
	if pid := c.panelIDHeader(); pid != "" {
		req.Header.Set("X-Panel-ID", pid)
	}
	req.Header.Set("X-Contract-Version", fmt.Sprint(ContractVersion))
	req.Header.Set("Accept", "text/event-stream")
	return hc.Do(req) // #nosec // address comes from trusted node record
}

// readEventStream parses one SSE body: frames separated by blank lines, ":"
// comments dropped, multi-line data joined with a newline. Every
// well-formed frame reaches on; its error ends the stream.
func readEventStream(body io.Reader, on func(NodeEvent) error) error {
	sc := bufio.NewScanner(body)
	sc.Buffer(make([]byte, 64*1024), eventFrameCap)
	var kind string
	var data []string
	frame := func() error {
		if kind == "" || len(data) == 0 {
			kind, data = "", data[:0]
			return nil
		}
		k := kind
		payload := strings.Join(data, "\n")
		kind, data = "", data[:0]
		var wire struct {
			Revision int64           `json:"revision"`
			Data     json.RawMessage `json:"data"`
		}
		if err := json.Unmarshal([]byte(payload), &wire); err != nil {
			return fmt.Errorf("node event data is not JSON: %w", err)
		}
		return on(NodeEvent{Kind: k, Revision: wire.Revision, Data: wire.Data})
	}
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		switch {
		case line == "":
			if err := frame(); err != nil {
				return err
			}
		case strings.HasPrefix(line, ":"):
			// keepalive comment
		case strings.HasPrefix(line, "event:"):
			kind = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		case strings.HasPrefix(line, "data:"):
			data = append(data, strings.TrimSpace(strings.TrimPrefix(line, "data:")))
		}
	}
	if err := sc.Err(); err != nil {
		return fmt.Errorf("node event stream ended: %w", err)
	}
	return frame()
}
