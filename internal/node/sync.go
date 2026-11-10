// Background sync operations (backend): traffic collection,
// limit pushing, stale-session cleanup.
package node

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"sort"
	"strconv"
	"time"
)

// PushHashKey is the node_usage JSON key holding per-node push hashes.
const PushHashKey = "push_hash"

// ReseedMarkerKey marks a user awaiting a baseline reseed after a usage reset
// (design §4.6): the next traffic pass seeds every node with delta 0.
const ReseedMarkerKey = "__reseed"

// EpochsKey is the reserved node_usage key holding per-node counter epochs.
const EpochsKey = "__epochs"

// IsReservedUsageKey reports whether a node_usage key is bookkeeping rather
// than a node id/name, so readers skip it.
func IsReservedUsageKey(key string) bool {
	return key == PushHashKey || key == ReseedMarkerKey || key == EpochsKey
}

// MaxPushBytes bounds one bulk /sync/users payload.
const MaxPushBytes = 1048576

type limitUser struct {
	id        int64
	name      string
	maxLogins int
	nodeUsage string
}

func allLimitUsers(db *sql.DB) []limitUser {
	rows, err := db.Query(`SELECT id, name, COALESCE(max_logins,0), COALESCE(node_usage,'{}') FROM User`)
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
	if err := rows.Err(); err != nil {
		return nil
	}
	return out
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

func pushLimitsBatch(n *Node, users []limitUser, panelID string) map[string]any {
	c := NodeClient(n, panelID)
	items := make([]map[string]any, 0, len(users))
	for _, u := range users {
		items = append(items, map[string]any{"id": strconv.FormatInt(u.id, 10), "max_logins": u.maxLogins})
	}
	res, err := do[LimitsBatchResponse](c, http.MethodPost, "/sync/users", map[string]any{"users": items}, reqOpts{timeout: LongTimeout, allowFail: true})
	if err != nil {
		return map[string]any{"node": n.Name, "applied": 0, "failed": len(users), "success": false}
	}
	failedItems := []any{}
	for _, f := range res.Failed {
		var v any
		if err := json.Unmarshal(f, &v); err == nil {
			failedItems = append(failedItems, v)
		}
	}
	data := map[string]any{"applied": res.Applied, "failed": failedItems}
	applied := intOf(data["applied"])
	return map[string]any{
		"node":         n.Name,
		"applied":      applied,
		"failed":       len(failedItems),
		"success":      applied+len(failedItems) >= len(users) && len(failedItems) == 0,
		"failed_items": data["failed"],
	}
}

// SyncAllUserLimits routes the manual action through forced full policy
// reconciliation, preserving compatible response keys. It also retains the
// legacy bulk limit push for contract compatibility.
func SyncAllUserLimits(db *sql.DB) map[string]any {
	res := ReconcileUserPolicies(db, time.Now(), true)
	users := allLimitUsers(db)
	nodes := getActiveNodes(db)
	var legacy map[string]any
	if len(nodes) > 0 && len(users) > 0 {
		pid := PanelIDFor(db)
		legacy = pushLimitsBatch(nodes[0], users, pid)
	}
	out := map[string]any{
		"total":   res.Total,
		"success": res.Applied,
		"skipped": res.Skipped,
		"applied": res.Applied,
		"failed":  res.Failed,
		"results": res.Results,
	}
	if legacy != nil {
		out["legacy_bulk"] = legacy
	}
	return out
}

// CleanStaleSessionsAllNodes removes stale markers across every node.
func CleanStaleSessionsAllNodes(db *sql.DB) map[string]any {
	nodes := getAllNodes(db)
	pid := PanelIDFor(db)
	share := FairShareTimeout(RequestFanoutDeadline, len(nodes), NodeFanoutLimit)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		n := n
		calls = append(calls, func() any {
			return cleanNodeSessions(n, pid, share)
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

func cleanNodeSessions(n *Node, pid string, share time.Duration) map[string]any {
	c := NodeClient(n, pid)
	data, err := c.GetSessions("", 8, share)
	if err != nil || data == nil {
		return map[string]any{"node": n.Name, "success": false, "error": "diagnostics unavailable", "removed": []string{}}
	}
	liveCNs := map[string]bool{}
	for _, s := range data.LiveSessions {
		cn := s.CommonName
		if cn == "" {
			cn = s.CN
		}
		if cn != "" {
			liveCNs[cn] = true
		}
	}
	staleSet := map[string]bool{}
	for _, m := range data.StaleMarkers {
		cn := m.CommonName
		if cn == "" {
			cn = m.CN
		}
		if cn != "" {
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
		res, err := c.DisconnectUser(cn, liveCNs[cn], 0)
		if err == nil {
			removed = append(removed, res.RemovedMarkers...)
		}
	}
	return map[string]any{"node": n.Name, "success": true, "removed": removed}
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
