// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"database/sql"
	"log"
	"strconv"
	"sync"
)

// RevocationResult summarizes one ProcessPendingRevocations pass.
type RevocationResult struct {
	Attempted    int
	Acknowledged int
	Failed       int

	FailedNodes []string
	Failures    []string
}

var revocationPassMu sync.Mutex

func ProcessPendingRevocations(db *sql.DB, limit int) RevocationResult {
	res := RevocationResult{
		FailedNodes: []string{},
		Failures:    []string{},
	}
	if db == nil {
		return res
	}
	if !revocationPassMu.TryLock() {
		return res
	}
	defer revocationPassMu.Unlock()

	if limit <= 0 {
		limit = 20
	}

	var hasTable int
	if err := db.QueryRow(`SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='PendingUserRevocation'`).Scan(&hasTable); err != nil || hasTable == 0 {
		return res
	}
	// If the table does not exist yet, there is nothing to retry.
	rows, err := db.Query(`SELECT node_id, user_id, user_uuid, user_name FROM PendingUserRevocation ORDER BY created_at, node_id, user_id LIMIT ?`, limit)
	if err != nil {
		log.Printf("revocations: query failed: %v", err)
		return res
	}
	type job struct {
		nodeID int64
		userID int64
		uuid   string
		name   string
	}
	var jobs []job
	for rows.Next() {
		var j job
		if err := rows.Scan(&j.nodeID, &j.userID, &j.uuid, &j.name); err != nil {
			continue
		}
		jobs = append(jobs, j)
	}
	_ = rows.Close()

	res.Attempted = len(jobs)
	pid := PanelIDFor(db)
	for _, j := range jobs {
		n := GetNodeByID(db, j.nodeID)
		if n == nil {
			_, _ = db.Exec(`DELETE FROM PendingUserRevocation WHERE node_id = ? AND user_id = ?`, j.nodeID, j.userID)
			res.Acknowledged++
			continue
		}
		c := NodeClient(n, pid)
		ok := c.DeleteUser(strconv.FormatInt(j.userID, 10))
		if ok {
			_, _ = db.Exec(`DELETE FROM PendingUserRevocation WHERE node_id = ? AND user_id = ?`, j.nodeID, j.userID)
			res.Acknowledged++
			continue
		}
		msg := "node did not acknowledge deletion"
		if cm := c.ConflictMsg(); cm != "" {
			msg = cm
		}
		_, _ = db.Exec(`UPDATE PendingUserRevocation SET last_error = ? WHERE node_id = ? AND user_id = ?`, msg, j.nodeID, j.userID)
		res.Failed++
		res.FailedNodes = append(res.FailedNodes, n.Name)
		res.Failures = append(res.Failures, n.Name+":"+strconv.FormatInt(j.userID, 10))
	}

	return res
}
