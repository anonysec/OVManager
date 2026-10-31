// Task 3: expired/depleted sweep (#5) + kick (#6). All helpers live beside the
// handlers in handler.go; this file only holds the three route handlers.
//
// Purge routes through the same delete path as the single delete (traffic
// rows, users row, DeleteUserOnAllNodes fan-out) — it never re-implements it,
// and one bad node is logged + counted, never fatal (same behavior as
// handleRemove since Task 6).
package users

import (
	"errors"
	"net/http"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// expiredHandler is GET /users/expired: users whose account is expired or
// quota-depleted (exactly the activationBlocked predicate — one source of
// truth for "this user is dead"), in the same JSON shape as the list handler.
func (h *Handler) expiredHandler(w http.ResponseWriter, r *http.Request) {
	res, err := h.Svc.DB().Query(`SELECT ` + userCols + ` FROM users ORDER BY id`)
	if err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
		return
	}
	conns := telemetry.Connections()
	out := make([]map[string]any, 0)
	for _, u := range scanAll(res) {
		if activationBlocked(u) != "" {
			out = append(out, u.live(conns))
		}
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "Expired users retrieved successfully",
		Data: map[string]any{
			"users":     out,
			"total":     len(out),
			"page":      1,
			"page_size": len(out),
		},
	})
}

// purge deletes every requested user through the single-delete path, one call
// to DeleteUserOnAllNodes per user (the panel's existing fan-out). Unknown ids
// are skipped; deleting all users is refused so one user always remains.
func (h *Handler) purge(w http.ResponseWriter, r *http.Request) {
	var req struct {
		UserIDs []string `json:"user_ids"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if len(req.UserIDs) == 0 {
		auth.WriteValidation(w, "user_ids", "Field required")
		return
	}

	var total int64
	if err := h.Svc.DB().QueryRow(`SELECT COUNT(*) FROM users`).Scan(&total); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not purge users")
		return
	}
	rows := make([]userRow, 0, len(req.UserIDs))
	seen := map[string]bool{}
	for _, uuidStr := range req.UserIDs {
		uuidStr = strings.TrimSpace(uuidStr)
		if seen[uuidStr] {
			continue
		}
		seen[uuidStr] = true
		if row, ok := h.byUUID(uuidStr); ok {
			rows = append(rows, row)
		}
	}
	if total <= int64(len(rows)) {
		auth.WriteDetail(w, http.StatusConflict, "You must keep at least one user — create another before deleting this one")
		return
	}

	deleted := 0
	failedUsers := 0
	keepLast := false
	skipped := map[string]bool{}
	for _, row := range rows {
		failed, err := h.deleteRow(row, true)
		if err != nil {
			failedUsers++
			keepLast = keepLast || errors.Is(err, errKeepLastUser)
			continue
		}
		for _, name := range failed {
			skipped[name] = true
		}
		deleted++
	}
	if deleted == 0 && keepLast {
		auth.WriteDetail(w, http.StatusConflict, "You must keep at least one user — create another before deleting this one")
		return
	}
	if deleted > 0 {
		telemetry.Publish("users", telemetry.KV{Key: "op", Val: "delete"})
	}
	list := make([]string, 0, len(skipped))
	for name := range skipped {
		list = append(list, name)
	}
	message := "Users purged successfully"
	if failedUsers > 0 {
		message = "Some users could not be purged"
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     message,
		Data:    map[string]any{"deleted": deleted, "failed": failedUsers, "nodes_skipped": list},
	})
}

// kickHandler serves the UUID routes and their /users/id/{id} aliases:
// revoke the user's sessions and kill their live connections on every
// reachable node, reporting how many were terminated. Zero terminated
// sessions is still a 200.
func (h *Handler) kickHandler(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	killed, failed := h.kickUserNodes(row)
	if killed > 0 {
		telemetry.Publish("users", telemetry.KV{Key: "op", Val: "connections"})
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "User kicked",
		Data:    map[string]any{"kicked": killed, "nodes_skipped": failed},
	})
}

// activeNodeIDs is the SELECT getActiveNodes builds from: active node ids,
// kept here so the users package can build the fan-out without touching
// internal/node (its exported GetNodeByID + NodeClient + GatherNodes pieces).
func (h *Handler) activeNodeIDs() []int64 {
	rows, err := h.Svc.DB().Query(`SELECT id FROM nodes WHERE status = 1`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var ids []int64
	for rows.Next() {
		var id int64
		if rows.Scan(&id) == nil {
			ids = append(ids, id)
		}
	}
	return ids
}

// kickUserNodes disconnects one user (by panel numeric id, the same uid space
// DeleteUserOnAllNodes uses) on every active node via the existing
// /sync/user/{uid}/disconnect plumbing. Returns the terminated session count
// and the names of nodes that could not be reached.
func (h *Handler) kickUserNodes(u userRow) (killed int, failed []string) {
	ids := h.activeNodeIDs()
	if len(ids) == 0 {
		return 0, nil
	}
	pid := node.PanelIDFor(h.Svc.DB())
	uid := strconv.FormatInt(u.ID, 10)

	nodes := make([]*node.Node, 0, len(ids))
	calls := make([]func() any, 0, len(ids))
	share := node.FairShareTimeout(node.RequestFanoutDeadline, len(ids), node.NodeFanoutLimit)
	for _, id := range ids {
		n := node.GetNodeByID(h.Svc.DB(), id)
		if n == nil {
			continue
		}
		nodes = append(nodes, n)
		calls = append(calls, func() any {
			return node.NodeClient(n, pid).DisconnectUser(uid, false, share)
		})
	}
	results := node.GatherNodes(calls, node.RequestFanoutDeadline)
	for i, item := range results {
		res, ok := item.(map[string]any)
		if !ok || len(res) == 0 {
			failed = append(failed, nodes[i].Name)
			continue
		}
		killed += killCountOf(res)
	}
	return killed, failed
}

// killCountOf reads the per-node disconnect response the way
// cleanNodeSessions reads it (removed_markers), plus the live-kill counter
// when the node reports one.
func killCountOf(res map[string]any) int {
	n := 0
	if list, ok := res["removed_markers"].([]any); ok {
		n += len(list)
	}
	if v, ok := res["killed_sessions"].(float64); ok {
		n += int(v)
	}
	return n
}
