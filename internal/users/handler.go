// The node fan-out half of each mutation lands with Phase 2; local DB state is
// authoritative here, so with zero nodes the responses match exactly.
package users

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/anonysec/OVManager/internal/accounting"
	"github.com/anonysec/OVManager/internal/audit"
	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/node"
	"github.com/anonysec/OVManager/internal/telemetry"
)

// Handler serves the /users routes.
type Handler struct {
	Svc *auth.Service
}

// NewHandler builds the users router.
func NewHandler(svc *auth.Service) *Handler {
	return &Handler{Svc: svc}
}

// Mount registers the users routes relative to the caller's prefix.
func (h *Handler) Mount(mux *http.ServeMux) {
	guard := h.Svc.RequireUser
	mux.HandleFunc("GET /users/next-username", guard(h.nextUsername))
	mux.HandleFunc("GET /users/traffic/top", guard(h.topTraffic))
	mux.HandleFunc("GET /users/{uuid}/traffic", guard(h.traffic))
	mux.HandleFunc("GET /users/expired", guard(h.expiredHandler))
	mux.HandleFunc("GET /users/{$}", guard(h.list))
	mux.HandleFunc("POST /users/{$}", guard(h.create))
	mux.HandleFunc("POST /users/{uuid}/activation", guard(h.issueActivationToken))
	mux.HandleFunc("POST /users/purge", guard(h.purge))
	mux.HandleFunc("POST /users/{uuid}/reset-usage", guard(h.resetUsage))
	mux.HandleFunc("PUT /users/{uuid}", guard(h.update))
	mux.HandleFunc("PUT /users/{uuid}/{$}", guard(h.update))
	// In Go 1.22+ ServeMux, "PUT /users/id/{id}" conflicts with "PUT /users/{uuid}/status"
	// because both match 3 segments like "/users/id/status". We dispatch them via a single
	// 2-wildcard handler.
	mux.HandleFunc("PUT /users/{first}/{second}", guard(func(w http.ResponseWriter, r *http.Request) {
		first := r.PathValue("first")
		second := r.PathValue("second")
		if second == "status" {
			r.SetPathValue("uuid", first)
			h.status(w, r)
			return
		}
		if first == "id" {
			r.SetPathValue("id", second)
			h.update(w, r)
			return
		}
		userNotFound(w)
	}))
	mux.HandleFunc("PUT /users/{first}/{second}/{$}", guard(func(w http.ResponseWriter, r *http.Request) {
		first := r.PathValue("first")
		second := r.PathValue("second")
		if first == "id" {
			r.SetPathValue("id", second)
			h.update(w, r)
			return
		}
		userNotFound(w)
	}))
	mux.HandleFunc("GET /users/{uuid}/sessions", guard(h.sessions))
	mux.HandleFunc("POST /users/{uuid}/disconnect", guard(h.kickHandler))
	mux.HandleFunc("POST /users/{uuid}/kick", guard(h.kickHandler))
	mux.HandleFunc("DELETE /users/{uuid}", guard(h.remove))
	mux.HandleFunc("POST /users/{uuid}/extend", guard(h.extend))

	// Explicit numeric-ID aliases avoid changing the meaning of an existing
	// UUID path that happens to contain only digits. Both forms use the same
	// authenticated handlers; restore intentionally remains UUID-only because
	// deleted users no longer have a live numeric key.
	const numeric = "/users/id/{id}"
	mux.HandleFunc("GET "+numeric+"/traffic", guard(h.traffic))
	mux.HandleFunc("POST "+numeric+"/reset-usage", guard(h.resetUsage))
	mux.HandleFunc("PUT "+numeric+"/status", guard(h.status))
	mux.HandleFunc("GET "+numeric+"/sessions", guard(h.sessions))
	mux.HandleFunc("POST "+numeric+"/disconnect", guard(h.kickHandler))
	mux.HandleFunc("POST "+numeric+"/kick", guard(h.kickHandler))
	mux.HandleFunc("DELETE "+numeric, guard(h.remove))
	mux.HandleFunc("POST "+numeric+"/extend", guard(h.extend))
}

// --- handlers ---

func (h *Handler) nextUsername(w http.ResponseWriter, r *http.Request) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "No username prefix configured"})
}

// topTraffic ranks users by billed bytes over the last N days.
func (h *Handler) topTraffic(w http.ResponseWriter, r *http.Request) {
	days := max(1, min(queryInt(r, "days", 30), 90))
	limit := max(1, min(queryInt(r, "limit", 10), 25))
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "Top traffic users retrieved",
		Data:    accounting.TopUsers(h.Svc.DB(), days, limit),
	})
}

func (h *Handler) sessions(w http.ResponseWriter, r *http.Request) {
	user, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	hours := max(1, min(queryInt(r, "hours", 8), 24*30))
	data := node.LoginDiagnostics(user.Name, h.Svc.DB(), hours)
	if found, ok := data["found"].(bool); !ok || !found {
		userNotFound(w)
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User session diagnostics", Data: data})
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request) {
	pageParam := r.URL.Query().Get("page")
	sizeParam := r.URL.Query().Get("page_size")
	search := strings.TrimSpace(r.URL.Query().Get("search"))
	serverFilter := pageParam != "" || sizeParam != "" || search != ""

	page, pageSize := 1, 100
	if pageParam != "" {
		if n, err := parsePositive(pageParam); err == nil {
			page = n
		}
	}
	if sizeParam != "" {
		if n, err := parsePositive(sizeParam); err == nil {
			pageSize = n
		}
	}

	var rows []userRow
	var total int64
	if serverFilter {
		like := "%" + escapeLike(search) + "%"
		if err := h.Svc.DB().QueryRowContext(r.Context(), `SELECT COUNT(*) FROM User WHERE name LIKE ? ESCAPE '\'`, like).Scan(&total); err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		res, err := h.Svc.DB().QueryContext(r.Context(), `SELECT `+userCols+` FROM User WHERE name LIKE ? ESCAPE '\' ORDER BY id LIMIT ? OFFSET ?`,
			like, pageSize, (page-1)*pageSize)
		if err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		rows = scanAll(res)
	} else {
		res, err := h.Svc.DB().QueryContext(r.Context(), `SELECT `+userCols+` FROM User ORDER BY id`)
		if err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		rows = scanAll(res)
		total = int64(len(rows))
	}

	conns := telemetry.Connections()
	out := make([]map[string]any, 0, len(rows))
	for _, u := range rows {
		out = append(out, u.live(conns))
	}
	respPage, respSize := 1, int(total)
	if serverFilter {
		respPage, respSize = page, pageSize
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "Users retrieved successfully",
		Data: map[string]any{
			"users":     out,
			"total":     total,
			"page":      respPage,
			"page_size": respSize,
		},
	})
}

func (h *Handler) issueActivationToken(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ExpiresDays *int `json:"expires_days"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	days := 7
	if req.ExpiresDays != nil {
		d := *req.ExpiresDays
		if d < 1 || d > 30 {
			auth.WriteValidation(w, "expires_days", "Input should be between 1 and 30")
			return
		}
		days = d
	}
	uuidStr := r.PathValue("uuid")
	var userID int64
	if err := h.Svc.DB().QueryRowContext(r.Context(), `SELECT id FROM User WHERE uuid = ?`, uuidStr).Scan(&userID); err != nil {
		userNotFound(w)
		return
	}
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "could not generate token")
		return
	}
	tokenHex := hex.EncodeToString(raw)
	hash := sha256.Sum256(raw)
	hashHex := hex.EncodeToString(hash[:])
	expiresAt := float64(time.Now().UnixNano())/1e9 + float64(days*24*60*60)
	if _, err := h.Svc.DB().ExecContext(r.Context(), `UPDATE User SET activation_token_hash = ?, activation_token_expires_at = ? WHERE id = ?`,
		hashHex, expiresAt, userID); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "could not persist token")
		return
	}
	audit.Record(h.Svc.DB(), h.actor(r), "User.ActivationIssue", "info",
		"Activation token issued.", map[string]any{"target": uuidStr, "days": days})
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Pragma", "no-cache")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "Activation token issued. Show it once; it will not be displayed again.",
		Data: map[string]any{
			"token":      tokenHex,
			"expires_at": time.Unix(int64(expiresAt), 0).UTC().Format(time.RFC3339),
		},
	})
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name       string  `json:"name"`
		Total      *int64  `json:"total"`
		Used       *int64  `json:"used"`
		MaxLogins  *int64  `json:"max_logins"`
		ExpiryDate *string `json:"expiry_date"`
		Tag        *string `json:"tag"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if n := len([]rune(req.Name)); n < 3 {
		auth.WriteValidation(w, "name", "String should have at least 3 characters")
		return
	} else if n > 64 {
		auth.WriteValidation(w, "name", "String should have at most 64 characters")
		return
	}
	if req.MaxLogins != nil && (*req.MaxLogins < 0 || *req.MaxLogins > 1000) {
		auth.WriteValidation(w, "max_logins", "Input should be between 0 and 1000")
		return
	}
	expiry := ""
	if req.ExpiryDate != nil && *req.ExpiryDate != "" {
		expiry = (*req.ExpiryDate)[:min(10, len(*req.ExpiryDate))]
		if _, err := time.Parse("2006-01-02", expiry); err != nil {
			auth.WriteValidation(w, "expiry_date", "Input should be a valid date")
			return
		}
	}

	name := strings.ReplaceAll(req.Name, " ", "_")
	var exists int64
	if err := h.Svc.DB().QueryRowContext(r.Context(), `SELECT COUNT(*) FROM User WHERE name = ?`, name).Scan(&exists); err == nil && exists > 0 {
		auth.WriteDetail(w, http.StatusConflict, "User with this name already exists")
		return
	}

	maxLogins := 0
	if req.MaxLogins != nil {
		maxLogins = int(*req.MaxLogins)
	}
	if req.Total != nil && *req.Total == 0 {
		req.Total = nil
	}
	var tag any
	if req.Tag != nil {
		if t := strings.TrimSpace(*req.Tag); t != "" {
			tag = t
		}
	}

	res, err := h.Svc.DB().ExecContext(r.Context(),
		`INSERT INTO User (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, tag)
		 VALUES (?, ?, ?, ?, 0, '{}', ?, ?, 1, ?)`,
		uuid.NewString(), name, req.Total, req.Used, maxLogins, expiry, tag,
	)
	if err != nil {
		auth.WriteDetail(w, http.StatusConflict, "User with this name already exists")
		return
	}
	id, _ := res.LastInsertId()
	row, _ := scanUser(h.Svc.DB().QueryRowContext(r.Context(), `SELECT `+userCols+` FROM User WHERE id = ?`, id))
	audit.Record(h.Svc.DB(), h.actor(r), "User.Create", "info",
		"User created.", map[string]any{"target": name, "max_logins": maxLogins})
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "create"})
	node.SyncUserPolicy(h.Svc.DB(), id, time.Now())
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "User created successfully. VPN config will be generated on first download.",
		Data:    row.base(),
	})
}

func (h *Handler) update(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	raw := map[string]json.RawMessage{}
	if !decodeRaw(w, r, &raw) {
		return
	}
	sent := func(key string) bool { _, ok := raw[key]; return ok }

	diffs := []string{}
	oldTotalGB := int64(0)
	if row.Total != nil {
		oldTotalGB = *row.Total / (1024 * 1024 * 1024)
	}
	oldMaxLogins := row.MaxLogins

	if sent("expiry_date") {
		if string(raw["expiry_date"]) == "null" {
			auth.WriteDetail(w, http.StatusUnprocessableEntity, "expiry_date cannot be null")
			return
		}
		var s string
		if err := json.Unmarshal(raw["expiry_date"], &s); err != nil {
			auth.WriteValidation(w, "expiry_date", "Input should be a valid date")
			return
		}
		if s != "" {
			if _, err := time.Parse("2006-01-02", s[:min(10, len(s))]); err != nil {
				auth.WriteValidation(w, "expiry_date", "Input should be a valid date")
				return
			}
		}
	}
	if sent("total") && string(raw["total"]) != "null" {
		var v int64
		if err := json.Unmarshal(raw["total"], &v); err != nil {
			auth.WriteValidation(w, "total", "Input should be a valid integer")
			return
		}
		if v < 0 {
			auth.WriteValidation(w, "total", "Input should be greater than or equal to 0")
			return
		}
		if v == 0 {
			row.Total = nil
		} else {
			newGB := v / (1024 * 1024 * 1024)
			if row.Total == nil || oldTotalGB != newGB {
				diffs = append(diffs, fmt.Sprintf("quota %dGB -> %dGB", oldTotalGB, newGB))
			}
			row.Total = &v
		}
	}
	if sent("total") && string(raw["total"]) == "null" {
		if row.Total != nil {
			diffs = append(diffs, fmt.Sprintf("quota %dGB -> unlimited", oldTotalGB))
		}
		row.Total = nil
	}
	if sent("max_logins") && string(raw["max_logins"]) != "null" {
		var v int64
		if err := json.Unmarshal(raw["max_logins"], &v); err != nil {
			auth.WriteValidation(w, "max_logins", "Input should be a valid integer")
			return
		}
		if v < 0 || v > 1000 {
			auth.WriteValidation(w, "max_logins", "Input should be between 0 and 1000")
			return
		}
		if oldMaxLogins != v {
			diffs = append(diffs, fmt.Sprintf("max logins %d -> %d", oldMaxLogins, v))
		}
		row.MaxLogins = v
	}
	if sent("tag") {
		var s string
		if err := json.Unmarshal(raw["tag"], &s); err != nil {
			auth.WriteValidation(w, "tag", "Input should be a valid string")
			return
		}
		if t := strings.TrimSpace(s); t != "" {
			row.Tag = sql.NullString{String: t, Valid: true}
		} else {
			row.Tag = sql.NullString{}
		}
	}
	if sent("expiry_date") {
		var s string
		_ = json.Unmarshal(raw["expiry_date"], &s)
		newDate := s[:min(10, len(s))]
		if row.ExpiryDate.String != newDate {
			diffs = append(diffs, fmt.Sprintf("expiry %s -> %s", row.ExpiryDate.String, newDate))
		}
		row.ExpiryDate = sql.NullString{String: newDate, Valid: true}
	}
	requestedStatus := row.IsActive != 0
	if sent("status") && string(raw["status"]) != "null" {
		var b bool
		if err := json.Unmarshal(raw["status"], &b); err != nil {
			auth.WriteValidation(w, "status", "Input should be a valid boolean")
			return
		}
		requestedStatus = b
	}
	row.IsActive = 0
	if requestedStatus && activationBlocked(row) == "" {
		row.IsActive = 1
	}

	if _, err := h.Svc.DB().ExecContext(r.Context(),
		`UPDATE User SET total = ?, max_logins = ?, expiry_date = ?, is_active = ?, tag = ? WHERE uuid = ?`,
		row.Total, row.MaxLogins, row.ExpiryDate.String, row.IsActive, nullTag(row.Tag), row.UUID,
	); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not update user")
		return
	}
	updateMsg := "User updated."
	if len(diffs) > 0 {
		updateMsg = fmt.Sprintf("User updated: %s", strings.Join(diffs, ", "))
	}
	audit.Record(h.Svc.DB(), h.actor(r), "User.Update", "info",
		updateMsg, map[string]any{"target": row.Name, "active": row.IsActive != 0, "changes": diffs})
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "update"})
	node.SyncUserPolicy(h.Svc.DB(), row.ID, time.Now())
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User updated successfully"})
}

func (h *Handler) status(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	var req struct {
		Name   string `json:"name"`
		Status *bool  `json:"status"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Status == nil {
		auth.WriteValidation(w, "status", "Field required")
		return
	}
	if *req.Status {
		if blocked := activationBlocked(row); blocked != "" {
			auth.WriteJSON(w, http.StatusOK, auth.Response{
				Success: false,
				Msg:     "Cannot activate: user is " + blocked,
			})
			return
		}
	}
	active := int64(0)
	if *req.Status {
		active = 1
	}
	if _, err := h.Svc.DB().ExecContext(r.Context(), `UPDATE User SET is_active = ? WHERE uuid = ?`, active, row.UUID); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not change user status")
		return
	}
	audit.Record(h.Svc.DB(), h.actor(r), "User.Status", "info",
		"User enabled or disabled.", map[string]any{"target": row.Name, "active": *req.Status})
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "status"})
	node.SyncUserPolicy(h.Svc.DB(), row.ID, time.Now())
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Changed user status successfully"})
}

func (h *Handler) resetUsage(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	// Keep per-node baselines and push_hash; zero only the counters, and set the
	// reseed marker so the next traffic pass seeds every node with delta 0
	// instead of re-accounting bytes the panel already counted (design §4.6).
	// OCC guard prevents a traffic pass landing between read and write from
	// clobbering the just-written baseline.
	for attempt := 0; attempt < 3; attempt++ {
		var used int64
		var state string
		if err := h.Svc.DB().QueryRowContext(r.Context(), `SELECT COALESCE(used,0), COALESCE(node_usage,'{}') FROM User WHERE uuid = ?`, row.UUID).Scan(&used, &state); err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not reset usage")
			return
		}
		data := map[string]json.RawMessage{}
		if json.Unmarshal([]byte(state), &data) != nil {
			data = map[string]json.RawMessage{}
		}
		data[node.ReseedMarkerKey] = json.RawMessage("true")
		merged := string(mustJSON(data))
		res, err := h.Svc.DB().ExecContext(r.Context(), `UPDATE User SET used = 0, last_node_usage = 0, node_usage = ? WHERE uuid = ? AND COALESCE(used,0) IS ? AND COALESCE(node_usage,'{}') IS ?`, merged, row.UUID, used, state)
		if err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not reset usage")
			return
		}
		if n, _ := res.RowsAffected(); n == 1 {
			audit.Record(h.Svc.DB(), h.actor(r), "User.ResetUsage", "info",
				"User usage reset.", map[string]any{"target": row.Name})
			telemetry.Publish("users", telemetry.KV{Key: "op", Val: "reset-usage"})
			node.SyncUserPolicy(h.Svc.DB(), row.ID, time.Now())
			auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User usage reset successfully"})
			return
		}
	}
	auth.WriteDetail(w, http.StatusConflict, "Could not reset usage: concurrent update")
}

func (h *Handler) remove(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	if _, err := h.deleteRow(row, false); err != nil {
		if errors.Is(err, errKeepLastUser) {
			auth.WriteDetail(w, http.StatusConflict, "You must keep at least one user — create another before deleting this one")
		} else if errors.Is(err, errUserAlreadyDeleted) {
			userNotFound(w)
		} else {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not delete user")
		}
		return
	}
	// Undo snapshot written inside DeleteAccount's transaction.
	audit.Record(h.Svc.DB(), h.actor(r), "User.Delete", "warning",
		"User deleted.", map[string]any{"target": row.Name})
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "delete"})
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User deleted successfully"})
}

func (h *Handler) extend(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Days  int64 `json:"days"`
		Bytes int64 `json:"bytes"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Days == 0 && req.Bytes == 0 || req.Days < 0 || req.Bytes < 0 {
		auth.WriteDetail(w, http.StatusUnprocessableEntity, "days or bytes must be greater than 0")
		return
	}
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	if req.Days != 0 {
		base := time.Now().UTC()
		if row.ExpiryDate.Valid && row.ExpiryDate.String != "" {
			if t, err := time.Parse("2006-01-02", row.date()); err == nil {
				base = t
			}
		}
		row.ExpiryDate = sql.NullString{String: base.AddDate(0, 0, int(req.Days)).Format("2006-01-02"), Valid: true}
	}
	if req.Bytes != 0 {
		var total int64
		if row.Total != nil {
			total = *row.Total
		}
		total += req.Bytes
		row.Total = &total
	}
	if _, err := h.Svc.DB().ExecContext(r.Context(), `UPDATE User SET total = ?, expiry_date = ? WHERE uuid = ?`,
		row.Total, row.ExpiryDate.String, row.UUID); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not extend user")
		return
	}
	row, _ = h.byUUID(row.UUID)
	telemetry.Publish("users", telemetry.KV{Key: "op", Val: "extend"})
	node.SyncUserPolicy(h.Svc.DB(), row.ID, time.Now())
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User updated", Data: row.base()})
}

func (h *Handler) traffic(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byPathUser(r)
	if !ok {
		userNotFound(w)
		return
	}
	total, perNode := aggregateNodeUsage(h.Svc.DB(), row)
	days := max(1, min(queryInt(r, "days", 30), 90))
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "User traffic history retrieved",
		Data: map[string]any{
			"days":       accounting.UserDailySeries(h.Svc.DB(), row.ID, days),
			"used":       deref(row.Used),
			"total_used": total,
			"per_node":   perNode,
			"total":      row.Total,
		},
	})
}

func aggregateNodeUsage(db *sql.DB, u userRow) (int64, []map[string]any) {
	nodeIDs := map[string]int64{}
	nodeNames := map[int64]string{}
	if res, err := db.Query(`SELECT id, name FROM Node`); err == nil {
		defer res.Close()
		for res.Next() {
			var name string
			var id int64
			if res.Scan(&id, &name) == nil {
				nodeIDs[name] = id
				nodeNames[id] = name
			}
		}
		_ = res.Err() // iteration errors are non-fatal here; partial node map is degraded but usable
	}
	var usage map[string]json.RawMessage
	if json.Unmarshal([]byte(u.NodeUsage), &usage) != nil {
		usage = nil
	}
	perNode := []map[string]any{}
	var total int64
	for key, raw := range usage {
		if node.IsReservedUsageKey(key) {
			continue
		}
		// New baselines key by node id; legacy/importer rows key by name.
		name := key
		var id any
		if parsed, err := strconv.ParseInt(key, 10, 64); err == nil {
			if resolved, ok := nodeNames[parsed]; ok {
				name = resolved
				id = parsed
			}
		} else if resolved, ok := nodeIDs[key]; ok {
			id = resolved
		}
		var used int64
		var state struct {
			Total int64 `json:"total"`
		}
		if json.Unmarshal(raw, &state) == nil {
			used = state.Total
		} else {
			_ = json.Unmarshal(raw, &used)
		}
		entry := map[string]any{"node_id": id, "name": name, "used": used}
		perNode = append(perNode, entry)
		total += used
	}
	if len(perNode) == 0 {
		return deref(u.Used), perNode
	}
	return total, perNode
}

// activationBlocked mirrors crud.activation_blocked: an expired or
// out-of-traffic account must never be active.
func activationBlocked(u userRow) string {
	if u.ExpiryDate.Valid && u.ExpiryDate.String != "" {
		if u.date() < time.Now().UTC().Format("2006-01-02") {
			return "expired"
		}
	}
	if u.Total != nil && *u.Total > 0 && *u.Total <= deref(u.Used) {
		return "out of traffic"
	}
	return ""
}

// --- small utilities ---

func decodeBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 64*1024)
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		auth.WriteValidation(w, "body", "JSON decode error")
		return false
	}
	return true
}

func decodeRaw(w http.ResponseWriter, r *http.Request, dst *map[string]json.RawMessage) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 64*1024)
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		auth.WriteValidation(w, "body", "JSON decode error")
		return false
	}
	return true
}

func scanAll(res *sql.Rows) []userRow {
	defer res.Close()
	var out []userRow
	for res.Next() {
		if u, err := scanUser(res); err == nil {
			out = append(out, u)
		}
	}
	return out
}

func deref(v *int64) int64 {
	if v == nil {
		return 0
	}
	return *v
}

func nullTag(t sql.NullString) any {
	if !t.Valid || t.String == "" {
		return nil
	}
	return t.String
}

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		return []byte("{}")
	}
	return b
}

func escapeLike(s string) string {
	s = strings.ReplaceAll(s, "\\", "\\\\")
	s = strings.ReplaceAll(s, "%", "\\%")
	return strings.ReplaceAll(s, "_", "\\_")
}

// queryInt reads a positive integer query param, falling back to def.
func queryInt(r *http.Request, key string, def int) int {
	if n, err := parsePositive(r.URL.Query().Get(key)); err == nil {
		return n
	}
	return def
}

func parsePositive(v string) (int, error) {
	n := 0
	for _, c := range v {
		if c < '0' || c > '9' {
			return 0, errNotNumber
		}
		n = n*10 + int(c-'0')
	}
	if n < 1 {
		return 0, errNotNumber
	}
	return n, nil
}

var errNotNumber = errString("not a positive integer")

type errString string

func (e errString) Error() string { return string(e) }
