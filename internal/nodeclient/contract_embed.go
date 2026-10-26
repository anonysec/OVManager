// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package nodeclient

import _ "embed"

// ContractJSON is the machine-readable form of Contract. It is the single
// authority for the panel↔node API: the node vendors a copy and its CI
// checks that the two agree. Embedding it keeps the published copy and the
// Go table in one place.
//
//go:embed contract.json
var ContractJSON []byte
