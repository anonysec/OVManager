// Background sync operations (backend/node/sync.py): traffic collection,
// limit pushing, stale-session cleanup.
package node

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
)

// PushHashKey is the node_usage JSON key holding per-node push hashes.
const PushHashKey = "push_hash"

// ReseedMarkerKey marks a user awaiting a baseline reseed after a usage reset
// (design §4.6): the next traffic pass seeds every node with delta 0.
const ReseedMarkerKey = "__reseed"

// IsReservedUsageKey reports whether a node_usage key is bookkeeping rather
// than a node id/name, so readers skip it.
func IsReservedUsageKey(key string) bool {
	return key == PushHashKey || key == ReseedMarkerKey
}

// DefaultBatchSize / MaxPushBytes bound one bulk /sync/users chunk.
const (
	DefaultBatchSize = 100
	MaxPushBytes     = 1048576
)

// GetUsersUsedTraffic returns per-user traffic counters from a node.
func GetUsersUsedTraffic(n *Node, db *sql.DB) map[string]any {
	return NodeClient(n, PanelIDFor(db)).GetUsage(0)
}

type limitUser struct {
	id        int64
	name      string
	maxLogins int
	nodeUsage string
}

func allLimitUsers(db *sql.DB) []limitUser {
	rows, err := db.Query(`SELECT id, name, COALESCE(max_logins,0), COALESCE(node_usage,'{}') FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []limitUser
	for rows.Next() {
		var u limitUser
		if err := rows.Scan(&u.id, &u.name, &u.maxLogins, &u.nodeUsage); err != nil {
			return out
		}
		out = append(out, u)
	}
	return out
}

// pushHash is sha256 over the state one sweep pushes for one user on one node.
func pushHash(uid string, name string, maxLogins int) string {
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%d", uid, name, maxLogins)))
	return hex.EncodeToString(sum[:])
}

func storedPushHashes(nodeUsage string) map[string]string {
	out := map[string]string{}
	var data map[string]any
	if json.Unmarshal([]byte(nodeUsage), &data) != nil {
		return out
	}
	if stored, ok := data[PushHashKey].(map[string]any); ok {
		for k, v := range stored {
			if s, ok := v.(string); ok {
				out[k] = s
			}
		}
	}
	return out
}

func batchSize(db *sql.DB) int {
	raw := getKV(db, "sync.batch_size")
	if n, err := strconv.Atoi(raw); err == nil && n >= 1 {
		return n
	}
	return DefaultBatchSize
}

func pushLimitsBatch(n *Node, users []limitUser, panelID string) map[string]any {
	c := NodeClient(n, panelID)
	items := make([]map[string]any, 0, len(users))
	for _, u := range users {
		items = append(items, map[string]any{"id": strconv.FormatInt(u.id, 10), "max_logins": u.maxLogins})
	}
	r := c.request("POST", "/sync/users", reqOpts{
		jsonBody:  map[string]any{"users": items},
		timeout:   LongTimeout,
		allowFail: true,
	})
	if r == nil {
		return map[string]any{"node": n.Name, "applied": 0, "failed": len(users), "success": false}
	}
	data := dataOf(r)
	applied := intOf(data["applied"])
	failedItems := []any{}
	if list, ok := data["failed"].([]any); ok {
		failedItems = list
	}
	return map[string]any{
		"node":         n.Name,
		"applied":      applied,
		"failed":       len(failedItems),
		"success":      applied+len(failedItems) >= len(users) && len(failedItems) == 0,
		"failed_items": failedItems,
	}
}

// SyncAllUserLimits pushes changed max_login limits to every reachable node.
func SyncAllUserLimits(db *sql.DB) map[string]any {
	users := allLimitUsers(db)
	nodes := getActiveNodes(db)

	type job struct {
		node  *Node
		users []limitUser
		want  map[int64]string
	}
	jobs := []job{}
	skipped := 0
	desired := 0

	for _, n := range nodes {
		chunk := []limitUser{}
		want := map[int64]string{}
		for _, u := range users {
			desired++
			h := pushHash(strconv.FormatInt(u.id, 10), u.name, u.maxLogins)
			if storedPushHashes(u.nodeUsage)[strconv.FormatInt(n.ID, 10)] == h {
				skipped++
				continue
			}
			chunk = append(chunk, u)
			want[u.id] = h
		}
		pid := PanelIDFor(db)
		for _, c := range ChunkBySize(chunk, batchSize(db), MaxPushBytes, func(u limitUser) int {
			return len(fmt.Sprintf(`{"id":"%d","max_logins":%d}`, u.id, u.maxLogins)) + 1
		}) {
			sub := map[int64]string{}
			for _, u := range c {
				sub[u.id] = want[u.id]
			}
			jobs = append(jobs, job{node: n, users: c, want: sub})
			_ = pid
		}
	}

	// No nodes: desired stays 0; every user counts as skipped only when nodes exist.
	if len(nodes) == 0 {
		skipped = 0
	}

	pid := PanelIDFor(db)
	calls := make([]func() any, 0, len(jobs))
	for _, j := range jobs {
		j := j
		calls = append(calls, func() any { return pushLimitsBatch(j.node, j.users, pid) })
	}
	raw := GatherBounded(calls)

	results := []any{}
	fresh := map[int64]map[string]string{}
	appliedTotal := 0
	for i, item := range raw {
		if err, ok := item.(error); ok {
			results = append(results, map[string]any{"success": false, "error": err.Error()})
			continue
		}
		res, _ := item.(map[string]any)
		results = append(results, res)
		if ok, _ := res["success"].(bool); ok {
			appliedTotal += intOf(res["applied"])
			for uid, h := range jobs[i].want {
				if fresh[uid] == nil {
					fresh[uid] = map[string]string{}
				}
				fresh[uid][strconv.FormatInt(jobs[i].node.ID, 10)] = h
			}
		}
	}

	mergePushHashes(db, users, fresh)

	successCount := 0
	for _, r := range results {
		if m, ok := r.(map[string]any); ok {
			if b, _ := m["success"].(bool); b {
				successCount++
			}
		}
	}
	return map[string]any{
		"total":   len(results),
		"success": successCount,
		"skipped": skipped,
		"applied": appliedTotal,
		"results": results,
	}
}

func mergePushHashes(db *sql.DB, users []limitUser, fresh map[int64]map[string]string) {
	if len(fresh) == 0 {
		return
	}
	for uid, hashes := range fresh {
		var oldState string
		if err := db.QueryRow(`SELECT COALESCE(node_usage,'{}') FROM users WHERE id = ?`, uid).Scan(&oldState); err != nil {
			continue
		}
		var data map[string]any
		if json.Unmarshal([]byte(oldState), &data) != nil {
			data = map[string]any{}
		}
		merged := map[string]any{}
		if stored, ok := data[PushHashKey].(map[string]any); ok {
			for k, v := range stored {
				merged[k] = v
			}
		}
		for k, v := range hashes {
			merged[k] = v
		}
		data[PushHashKey] = merged
		canonical, _ := json.Marshal(sortedJSON(data))
		_, _ = db.Exec(
			`UPDATE users SET node_usage = ? WHERE id = ? AND COALESCE(node_usage,'{}') = ?`,
			string(canonical), uid, oldState,
		)
	}
}

// sortedJSON renders a map deterministically (json.Marshal already sorts keys).
func sortedJSON(data map[string]any) map[string]any { return data }

// CleanStaleSessionsAllNodes removes stale markers across every node.
func CleanStaleSessionsAllNodes(db *sql.DB) map[string]any {
	nodes := getAllNodes(db)
	pid := PanelIDFor(db)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			return cleanNodeSessions(n, pid)
		})
	}
	raw := GatherNodes(calls, RequestFanoutDeadline)
	results := []any{}
	removedTotal := 0
	for _, item := range raw {
		if err, ok := item.(error); ok {
			results = append(results, map[string]any{"success": false, "error": err.Error()})
			continue
		}
		res, _ := item.(map[string]any)
		results = append(results, res)
		if removed, ok := res["removed"].([]string); ok {
			removedTotal += len(removed)
		}
	}
	return map[string]any{"nodes": results, "removed_total": removedTotal}
}

func cleanNodeSessions(n *Node, pid string) map[string]any {
	c := NodeClient(n, pid)
	data := c.GetSessions("", 8, 0)
	if data == nil {
		return map[string]any{"node": n.Name, "success": false, "error": "diagnostics unavailable", "removed": []string{}}
	}
	liveCNs := map[string]bool{}
	for _, s := range sessionList(data["live_sessions"]) {
		if cn, ok := s["common_name"].(string); ok && cn != "" {
			liveCNs[cn] = true
		}
	}
	staleSet := map[string]bool{}
	for _, m := range sessionList(data["stale_markers"]) {
		if cn, ok := m["common_name"].(string); ok && cn != "" {
			staleSet[cn] = true
		}
	}
	stale := make([]string, 0, len(staleSet))
	for cn := range staleSet {
		stale = append(stale, cn)
	}
	sort.Strings(stale)
	removed := []string{}
	for _, cn := range stale {
		res := c.DisconnectUser(cn, liveCNs[cn])
		if list, ok := res["removed_markers"].([]any); ok {
			for _, m := range list {
				if s, ok := m.(string); ok {
					removed = append(removed, s)
				}
			}
		}
	}
	return map[string]any{"node": n.Name, "success": true, "removed": removed}
}

func sessionList(v any) []map[string]any {
	list, ok := v.([]any)
	if !ok {
		return nil
	}
	out := make([]map[string]any, 0, len(list))
	for _, item := range list {
		if m, ok := item.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

func intOf(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case int64:
		return int(n)
	case json.Number:
		i, _ := n.Int64()
		return int(i)
	}
	return 0
}
