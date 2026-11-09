// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"encoding/json"
	"sort"
)

// ContractJSONRow is one row of the embedded contract.json.
type ContractJSONRow struct {
	Method        string   `json:"method"`
	Path          string   `json:"path"`
	Query         []string `json:"query,omitempty"`
	Request       []string `json:"request"`
	Response      []string `json:"response"`
	ResponseItems []string `json:"response_items,omitempty"`
	RequestAt     string   `json:"request_at"`
	ResponseAt    []string `json:"response_at"`
	ResponseRaw   bool     `json:"response_raw,omitempty"`
	Note          string   `json:"note,omitempty"`
}

// ContractJSONRows parses the Go table into the embedded JSON shape.
func ContractJSONRows() []ContractJSONRow {
	rows := make([]ContractJSONRow, 0, len(Contract))
	for _, c := range Contract {
		r := ContractJSONRow{
			Method:        c.Method,
			Path:          c.Path,
			Query:         c.Query,
			Request:       c.Request,
			Response:      c.Response,
			ResponseItems: c.ResponseItems,
			RequestAt:     c.RequestAt,
			ResponseAt:    c.ResponseAt,
			ResponseRaw:   c.ResponseRaw,
			Note:          c.Note,
		}
		if r.Request == nil {
			r.Request = []string{}
		}
		if r.Response == nil {
			r.Response = []string{}
		}
		if r.ResponseAt == nil {
			r.ResponseAt = []string{}
		}
		rows = append(rows, r)
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Path != rows[j].Path {
			return rows[i].Path < rows[j].Path
		}
		return rows[i].Method < rows[j].Method
	})
	return rows
}

// MarshalContractJSON serializes the Go table to JSON at init.
func MarshalContractJSON() []byte {
	rows := ContractJSONRows()
	data, _ := json.MarshalIndent(rows, "", "  ")
	return append(data, '\n')
}
