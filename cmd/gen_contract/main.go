// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Command gen_contract writes internal/node/contract.json from the Go
// contract table. The table is the single source of truth; this file is a
// derived artifact that the release publishes and the node's CI diffs
// against.
//
// Usage:
//
//	gen_contract [--check] [path]
package main

import (
	"fmt"
	"os"

	"github.com/anonysec/OVManager/internal/node"
)

func main() {
	path := "internal/node/contract.json"
	check := false
	for _, arg := range os.Args[1:] {
		switch arg {
		case "--check":
			check = true
		default:
			path = arg
		}
	}
	data := node.ContractJSON
	if check {
		current, err := os.ReadFile(path)
		if err != nil || string(current) != string(data) {
			fmt.Fprintln(os.Stderr, "contract.json is stale; run: make contract")
			os.Exit(1)
		}
		return
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
