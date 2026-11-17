// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import "testing"

func TestNodeClientEmptyPanelIDClearsCachedHeader(t *testing.T) {
	resetForTests()
	defer resetForTests()
	n := &Node{ID: 9, Name: "n", Address: "127.0.0.1", Port: 1, Key: "k"}
	c := NodeClient(n, "panel-a")
	if c == nil {
		t.Fatal("NodeClient returned nil")
	}
	if got := c.panelIDHeader(); got != "panel-a" {
		t.Fatalf("panelIDHeader = %q, want panel-a", got)
	}
	c = NodeClient(n, "")
	if got := c.panelIDHeader(); got != "" {
		t.Fatalf("panelIDHeader after empty panel ID = %q, want empty", got)
	}
}
