// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Package nodeclient is the OUTBOUND HTTP client to an OVNode agent.
// It is a leaf: no database/sql, no panel domain logic.
package nodeclient

// Target is the minimal node description the client needs.
// It is owned by nodeclient; internal/nodes → nodeclient cannot cycle.
type Target struct {
	ID         int64
	Name       string
	Address    string
	TunnelAddr string
	Protocol   string
	OVPNPort   int
	Port       int
	APIKey     string
	ServerCA   string
	PanelID    string
}
