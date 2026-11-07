// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package main

import (
	"fmt"
	"os"

	"github.com/anonysec/OVManager/go/internal/node"
)

func main() {
	data := node.GenerateContractJSON()
	path := "internal/node/contract.gen.json"
	if len(os.Args) > 1 {
		path = os.Args[1]
	}
	if len(os.Args) > 2 && os.Args[2] == "--check" {
		current, err := os.ReadFile(path)
		if err != nil || string(current) != string(data) {
			fmt.Fprintln(os.Stderr, "contract.json is stale; regenerate it")
			os.Exit(1)
		}
		return
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
