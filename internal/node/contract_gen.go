// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"encoding/json"
	"sort"
)

// contractJSONRow is one row of the generated contract.json.
type contractJSONRow struct {
	Method      string   `json:"method"`
	Path        string   `json:"path"`
	Request     []string `json:"request"`
	Response    []string `json:"response"`
	RequestAt   string   `json:"request_at"`
	ResponseAt  []string `json:"response_at"`
	ResponseRaw bool     `json:"response_raw,omitempty"`
	Note        string   `json:"note,omitempty"`
}

// GenerateContractJSON serializes the contract table to the JSON the node
// vendors. Generated at release time; drift becomes a red build, not a
// runtime surprise.
func GenerateContractJSON() []byte {
	rows := make([]contractJSONRow, 0, len(Contract))
	for _, c := range Contract {
		r := contractJSONRow{
			Method:     c.Method,
			Path:       c.Path,
			Request:    c.Request,
			Response:   c.Response,
			RequestAt:  c.RequestAt,
			ResponseAt: c.ResponseAt,
			Note:       c.Note,
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
	data, _ := json.MarshalIndent(rows, "", "  ")
	return append(data, '\n')
}
