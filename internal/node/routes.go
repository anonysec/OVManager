// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/audit"
	"github.com/anonysec/OVManager/go/internal/auth"
)

// Handler serves the /nodes routes; it borrows the auth service's DB handle
// and middleware.
type Handler struct {
	svc          *auth.Service
	OnNodeChange func(op string)
}

func (h *Handler) notifyChange(op string) {
	if h != nil && h.OnNodeChange != nil {
		h.OnNodeChange(op)
	}
}

// NewHandler builds the node router over the shared auth service.
func NewHandler(svc *auth.Service) *Handler {
	if svc != nil {
		AuditDB = svc.DB
	}
	return &Handler{svc: svc}
}

// Mount registers the /nodes routes relative to the caller's prefix.
func (h *Handler) Mount(mux *http.ServeMux) {
	owner := func(fn http.HandlerFunc) http.HandlerFunc { return h.svc.RequireOwner(fn) }
	user := func(fn http.HandlerFunc) http.HandlerFunc { return h.svc.RequireUser(fn) }

	h.register(mux, "POST /nodes/", owner(h.handleAddNode))
	h.register(mux, "POST /nodes", owner(h.handleAddNode))
	h.register(mux, "POST /nodes/test", owner(h.handleTestNode))
	h.register(mux, "PUT /nodes/{node_id}", owner(h.handleUpdateNode))
	h.register(mux, "POST /nodes/{node_id}/repin", owner(h.handleRepin))
	h.register(mux, "PUT /nodes/{node_id}/dns", owner(h.handleNodeDNS))
	h.register(mux, "PUT /nodes/{node_id}/ipv6", owner(h.handleNodeIPv6))
	h.register(mux, "PUT /nodes/{node_id}/ports", owner(h.handleNodePorts))
	h.register(mux, "POST /nodes/{node_id}/restart", owner(h.handleNodeRestart))
	h.register(mux, "POST /nodes/{node_id}/renew-cert", owner(h.handleNodeRenewCert))
	h.register(mux, "POST /nodes/{node_id}/update", owner(h.handleNodeUpdate))
	h.register(mux, "GET /nodes/", owner(h.handleListNodes))
	h.register(mux, "GET /nodes", owner(h.handleListNodes))
	h.register(mux, "GET /nodes/ovpn/{uuid}/{node_id}", user(h.handleDownloadOVPN))
	h.register(mux, "GET /nodes/ovpn/id/{user_id}/{node_id}", user(h.handleDownloadOVPN))
	h.register(mux, "GET /nodes/ovpn-all/{node_id}", owner(h.handleDownloadAllOVPN))
	h.register(mux, "GET /nodes/{first}/{second}", owner(h.handleNodeSubresource))
	h.register(mux, "POST /nodes/{node_id}/restore", owner(h.handleRestoreNode))
	h.register(mux, "DELETE /nodes/{node_id}", owner(h.handleDeleteNode))
}

// handleNodeSubresource owns the "/nodes/{id}/<word>" GET routes.
//
// Go's ServeMux cannot rank "/nodes/ovpn-all/{id}" above "/nodes/{id}/status"
// (each is more specific in a different segment) and panics at registration,
// while FastAPI resolved the overlap by declaration order. Both live here:
// "/nodes/ovpn-all/{id}" is a strict subset of "/nodes/{first}/{second}", so it
// wins on specificity, and everything else lands in this switch.
func (h *Handler) handleNodeSubresource(w http.ResponseWriter, r *http.Request) {
	r.SetPathValue("node_id", r.PathValue("first"))
	switch r.PathValue("second") {
	case "status":
		h.handleNodeStatus(w, r)
	case "logs":
		h.handleNodeLogs(w, r)
	default:
		auth.WriteDetail(w, http.StatusNotFound, "Not Found")
	}
}

func (h *Handler) register(mux *http.ServeMux, pattern string, fn http.HandlerFunc) {
	mux.HandleFunc(pattern, fn)
}

func (h *Handler) nodeByID(r *http.Request) *Node {
	id, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		return nil
	}
	return GetNodeByID(h.svc.DB(), id)
}

func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)
	return json.NewDecoder(r.Body).Decode(v) == nil
}

func (h *Handler) handleAddNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	if req.Cert == nil || *req.Cert == "" {
		auth.WriteValidation(w, "cert", "A node certificate (PEM) is required to add a node")
		return
	}
	if req.Name == "" || strings.TrimSpace(req.Name) == "" {
		auth.WriteValidation(w, "name", "Node name is required")
		return
	}
	if getNodeByName(h.svc.DB(), req.Name) != nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: fmt.Sprintf("A node named '%s' already exists. Choose a different name.", req.Name)})
		return
	}
	ok, msg := AddNodeHandler(req, h.svc.DB())
	if ok {
		h.notifyChange("create")
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node added successfully"})
		return
	}
	if msg == "" {
		msg = "Node unreachable — install offline and configure after registration."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: msg})
}

func (h *Handler) handleTestNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	if strings.TrimSpace(req.key()) == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "API key is required."})
		return
	}
	serverCA := ""
	if req.Cert != nil && strings.TrimSpace(*req.Cert) != "" {
		serverCA = strings.TrimSpace(*req.Cert)
	} else {
		serverCA = FetchServerCert(req.Address, req.port(), 5*time.Second)
		if serverCA == "" {
			auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Could not fetch certificate from node."})
			return
		}
	}
	fp := CertFingerprint(serverCA)
	expectedFP := ""
	if req.ExpectedFingerprint != nil {
		expectedFP = strings.TrimSpace(*req.ExpectedFingerprint)
	}
	if expectedFP == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{
			Success: false,
			Msg:     "Certificate fetched for TOFU pinning. Please verify and confirm fingerprint before sending API key.",
			Data: map[string]any{
				"confirmation_required": true,
				"cert":                  serverCA,
				"fingerprint":           fp,
			},
		})
		return
	}
	if normalizeFingerprint(expectedFP) != normalizeFingerprint(fp) {
		auth.WriteJSON(w, http.StatusOK, auth.Response{
			Success: false,
			Msg:     fmt.Sprintf("Certificate fingerprint mismatch: expected %s, got %s", expectedFP, fp),
		})
		return
	}
	c, err := NewClient(req.Address, req.port(), req.key(), serverCA, PanelIDFor(h.svc.DB()), 0)
	if err != nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Invalid address: " + err.Error()})
		return
	}
	if c.CheckNode() {
		data := map[string]any{"reachable": true}
		if serverCA != "" {
			data["cert"] = serverCA
		}
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node is reachable.", Data: data})
		return
	}
	msg := c.ConflictMsg()
	if msg == "" {
		msg = "Node unreachable — check address (public IP, not 10.x/192.168.x unless shared LAN), service port (2083, not the 1194 VPN port), and the exact API key."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: msg})
}

func (h *Handler) handleUpdateNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	id, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if clash := getNodeByName(h.svc.DB(), req.Name); clash != nil && clash.ID != id {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: fmt.Sprintf("Another node is already named '%s'.", req.Name)})
		return
	}
	ok, msg := UpdateNodeHandler(id, req, h.svc.DB())
	if ok {
		h.notifyChange("update")
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: ok, Msg: msg})
}

func (h *Handler) handleNodeStatus(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node status retrieved successfully", Data: GetNodeStatus(h.svc.DB(), n.ID)})
}

type repinRequest struct {
	ExpectedFingerprint *string `json:"expected_fingerprint"`
	Confirm             *bool   `json:"confirm"`
}

func (h *Handler) handleRepin(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	var req repinRequest
	if r.Body != nil {
		_ = json.NewDecoder(io.LimitReader(r.Body, 64<<10)).Decode(&req)
	}

	host, port, _ := parseAddress(n.Address, n.Port)
	newPEM := FetchServerCert(host, port, 5*time.Second)
	if newPEM == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Could not fetch the node's certificate."})
		return
	}

	oldFP := CertFingerprint(n.ServerCA.String)
	newFP := CertFingerprint(newPEM)

	expectedFP := ""
	if req.ExpectedFingerprint != nil {
		expectedFP = strings.TrimSpace(*req.ExpectedFingerprint)
	}

	if expectedFP == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{
			Success: false,
			Msg:     "Certificate re-pin requires explicit confirmation. Please verify the new certificate fingerprint.",
			Data: map[string]any{
				"confirmation_required": true,
				"old_fingerprint":       oldFP,
				"new_fingerprint":       newFP,
				"prompt":                "Submit expected_fingerprint matching the new certificate to confirm re-pin",
			},
		})
		return
	}

	if expectedFP != "" && normalizeFingerprint(expectedFP) != normalizeFingerprint(newFP) {
		auth.WriteJSON(w, http.StatusOK, auth.Response{
			Success: false,
			Msg:     fmt.Sprintf("Fingerprint mismatch: expected %s, got %s", expectedFP, newFP),
			Data: map[string]any{
				"old_fingerprint": oldFP,
				"new_fingerprint": newFP,
			},
		})
		return
	}

	_, _ = h.svc.DB().Exec(`UPDATE nodes SET server_ca = ? WHERE id = ?`, newPEM, n.ID)

	actor := "owner"
	if h.svc != nil {
		if u, ok := h.svc.CurrentUser(r); ok && u.Username != "" {
			actor = u.Username
		}
	}
	audit.Record(h.svc.DB(), actor, "node.repin", "warning",
		fmt.Sprintf("Node %s (ID %d) certificate repinned by %s. Old fingerprint: %s, New fingerprint: %s", n.Name, n.ID, actor, oldFP, newFP),
		map[string]any{
			"node_id":         n.ID,
			"node_name":       n.Name,
			"old_fingerprint": oldFP,
			"new_fingerprint": newFP,
			"actor":           actor,
		})

	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "Certificate pin updated.",
		Data: map[string]any{
			"repinned":        true,
			"old_fingerprint": oldFP,
			"new_fingerprint": newFP,
		},
	})
}

func (h *Handler) handleNodeLogs(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	level := r.URL.Query().Get("level")
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit == 0 {
		limit = 100
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node logs retrieved successfully", Data: c.GetLogs(level, limit)})
}

func (h *Handler) handleNodeDNS(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DNS1 *string `json:"dns1"`
		DNS2 *string `json:"dns2"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.DNS1 == nil && req.DNS2 == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide dns1 and/or dns2."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	applied := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, DNS1: req.DNS1, DNS2: req.DNS2})
	if applied != true {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "The node rejected the DNS update — check the addresses are valid IPs and that the node is reachable."})
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "DNS settings applied on the node.", Data: map[string]any{"dns1": req.DNS1, "dns2": req.DNS2}})
}

func (h *Handler) handleNodeIPv6(w http.ResponseWriter, r *http.Request) {
	var req struct {
		EnableIPv6 *bool   `json:"enable_ipv6"`
		IPv6Prefix *string `json:"ipv6_prefix"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.EnableIPv6 == nil && req.IPv6Prefix == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide enable_ipv6 and/or ipv6_prefix."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	applied := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, EnableIPv6: req.EnableIPv6, IPv6Prefix: req.IPv6Prefix})
	if applied != true {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "The node rejected the IPv6 update — check the prefix is a valid IPv6 network and that the node is reachable."})
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "IPv6 settings applied on the node.", Data: map[string]any{"enable_ipv6": req.EnableIPv6, "ipv6_prefix": req.IPv6Prefix}})
}

func (h *Handler) handleNodePorts(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ExtraPorts *string `json:"extra_ports"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.ExtraPorts == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide extra_ports — a comma-separated port list, or an empty string to clear."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	answer := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, ExtraPorts: req.ExtraPorts, ReturnEnvelope: true})
	if answer == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Node unreachable — the ports were not changed."})
		return
	}
	env, _ := answer.(map[string]any)
	success, _ := env["success"].(bool)
	msg, _ := env["msg"].(string)
	if msg == "" {
		if success {
			msg = "Extra VPN ports applied on the node."
		} else {
			msg = "The node rejected the extra ports."
		}
	}
	if success {
		// Persist extra_ports in the database
		_, _ = h.svc.DB().Exec(`UPDATE nodes SET extra_ports = ? WHERE id = ?`, *req.ExtraPorts, n.ID)
		n.ExtraPorts = *req.ExtraPorts
	}
	data := env["data"]
	if data == nil && success {
		data = map[string]any{"extra_ports": *req.ExtraPorts}
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: success, Msg: msg, Data: data})
}

func (h *Handler) nodeEnvelopeAction(w http.ResponseWriter, r *http.Request, call func(*Client) map[string]any, unreachable string) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	answer := call(c)
	if answer == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: unreachable})
		return
	}
	success, _ := answer["success"].(bool)
	msg, _ := answer["msg"].(string)
	if msg == "" {
		msg = "Request processed."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: success, Msg: msg, Data: answer["data"]})
}

func (h *Handler) handleNodeRestart(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.RestartVPN() }, "Node unreachable — the restart was not requested.")
}

func (h *Handler) handleNodeRenewCert(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.RenewServerCert() }, "Node unreachable — nothing was renewed.")
}

func (h *Handler) handleNodeUpdate(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.TriggerUpdate() }, "Node unreachable — the update was not started.")
}

func (h *Handler) handleListNodes(w http.ResponseWriter, r *http.Request) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Nodes retrieved successfully", Data: listNodes(h.svc.DB())})
}

func (h *Handler) handleDeleteNode(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Failed to delete node"})
		return
	}
	ok := DeleteNodeHandler(n.ID, h.svc.DB())
	msg := "Node deleted successfully"
	if !ok {
		msg = "Failed to delete node"
	} else {
		h.notifyChange("delete")
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: ok, Msg: msg})
}

// handleRestoreNode restores a node deleted within the undo window.
func (h *Handler) handleRestoreNode(w http.ResponseWriter, r *http.Request) {
	id, ok := parsePositiveRouteID(r.PathValue("node_id"))
	if !ok {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Invalid node id"})
		return
	}
	ok2, msg := RestoreNodeHandler(id, h.svc.DB())
	if ok2 {
		h.notifyChange("restore")
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: ok2, Msg: msg})
}

func parsePositiveRouteID(raw string) (int64, bool) {
	if raw == "" {
		return 0, false
	}
	for i := 0; i < len(raw); i++ {
		if raw[i] < '0' || raw[i] > '9' {
			return 0, false
		}
	}
	id, err := strconv.ParseInt(raw, 10, 64)
	return id, err == nil && id > 0
}

func (h *Handler) handleDownloadOVPN(w http.ResponseWriter, r *http.Request) {
	uuid := r.PathValue("uuid")
	nodeID, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "OVPN file not found")
		return
	}
	userQuery := `SELECT id, is_active, total, used, expiry_date FROM users WHERE uuid = ?`
	var userLookup any = uuid
	if rawID := r.PathValue("user_id"); rawID != "" {
		id, ok := parsePositiveRouteID(rawID)
		if !ok {
			auth.WriteDetail(w, http.StatusNotFound, "User not found")
			return
		}
		userQuery = `SELECT id, is_active, total, used, expiry_date FROM users WHERE id = ?`
		userLookup = id
	}
	var userID int64
	var active bool
	var total, used sql.NullInt64
	var expiry sql.NullString
	if err := h.svc.DB().QueryRow(userQuery, userLookup).Scan(&userID, &active, &total, &used, &expiry); err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "User not found")
		return
	}
	// Expiry gate mirrors the subscription page (sub.subUser): expired users are
	// refused before the disabled/quota checks.
	if expiry.Valid && expiry.String != "" {
		raw := expiry.String
		if len(raw) > 10 {
			raw = raw[:10]
		}
		if raw < time.Now().Format("2006-01-02") {
			auth.WriteDetail(w, http.StatusForbidden, "User account has expired")
			return
		}
	}
	if !active {
		auth.WriteDetail(w, http.StatusForbidden, "User account is not active")
		return
	}
	if total.Valid && used.Int64 >= total.Int64 {
		auth.WriteDetail(w, http.StatusForbidden, "User traffic limit reached")
		return
	}
	content := DownloadOVPNClient(userID, nodeID, h.svc.DB())
	if content == nil {
		auth.WriteDetail(w, http.StatusNotFound, "OVPN file not found")
		return
	}
	w.Header().Set("Content-Type", "application/x-openvpn-profile")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%d.ovpn"`, userID))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(content)
}

func (h *Handler) handleDownloadAllOVPN(w http.ResponseWriter, r *http.Request) {
	nodeID, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found or configs unavailable")
		return
	}
	n := GetNodeByID(h.svc.DB(), nodeID)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found or configs unavailable")
		return
	}
	content := DownloadAllOVPNClients(nodeID, h.svc.DB())
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s_all_clients.zip"`, n.Name))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(content)
}
