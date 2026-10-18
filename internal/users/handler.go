// Package users ports backend/routers/users.py + backend/db/crud/users.py.
//
// The node fan-out half of each mutation lands with Phase 2; local DB state is
// authoritative here, so with zero nodes the responses match Python exactly.
package users

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/node"
)

// Handler serves the /users routes.
type Handler struct {
	Svc *auth.Service
	mu  sync.Mutex
	// ponytail: in-memory Undo registry, per-process like the Python one; move
	// to a table when the panel runs multi-worker.
	deleted map[string]deletedUser
}

type deletedUser struct {
	at   time.Time
	snap userRow
}

// backend/routers/users.py undo window.
const (
	deletedTTL = 120 * time.Second
	deletedMax = 50
)

// NewHandler builds the users router.
func NewHandler(svc *auth.Service) *Handler {
	return &Handler{Svc: svc, deleted: map[string]deletedUser{}}
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
	mux.HandleFunc("POST /users/purge", guard(h.purge))
	mux.HandleFunc("POST /users/{uuid}/reset-usage", guard(h.resetUsage))
	mux.HandleFunc("PUT /users/{uuid}", guard(h.update))
	mux.HandleFunc("PUT /users/{uuid}/{$}", guard(h.update))
	mux.HandleFunc("PUT /users/{uuid}/status", guard(h.status))
	mux.HandleFunc("GET /users/{uuid}/sessions", guard(h.sessions))
	mux.HandleFunc("POST /users/{uuid}/disconnect", guard(h.disconnect))
	mux.HandleFunc("POST /users/{uuid}/kick", guard(h.kickHandler))
	mux.HandleFunc("DELETE /users/{uuid}", guard(h.remove))
	mux.HandleFunc("POST /users/{uuid}/restore", guard(h.restore))
	mux.HandleFunc("POST /users/{uuid}/extend", guard(h.extend))
}

// userRow is the scanned users table row (backend/db/models.py User).
type userRow struct {
	ID            int64
	UUID          string
	Name          string
	Total         *int64
	Used          *int64
	LastNodeUsage int64
	NodeUsage     string
	MaxLogins     int64
	ExpiryDate    sql.NullString
	IsActive      int64
	LastOnline    sql.NullString
	Tag           sql.NullString
}

const userCols = `id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, last_online, tag`

func scanUser(row interface{ Scan(...any) error }) (userRow, error) {
	var u userRow
	err := row.Scan(&u.ID, &u.UUID, &u.Name, &u.Total, &u.Used, &u.LastNodeUsage, &u.NodeUsage,
		&u.MaxLogins, &u.ExpiryDate, &u.IsActive, &u.LastOnline, &u.Tag)
	return u, err
}

// base renders the Users response model (backend/schema/api.py).
func (u userRow) base() map[string]any {
	return map[string]any{
		"id":          u.ID,
		"name":        u.Name,
		"is_active":   u.IsActive != 0,
		"total":       u.Total,
		"used":        u.Used,
		"max_logins":  u.MaxLogins,
		"expiry_date": u.date(),
		"uuid":        u.UUID,
		"last_online": u.lastOnline(),
		"tag":         u.tag(),
	}
}

// live adds the panel-only connection fields (routers/users.py serialize()).
//
// ponytail: active_connections stays 0 until the live collector lands in
// Phase 2/3 (backend/operations/observability/live.py).
func (u userRow) live() map[string]any {
	m := u.base()
	m["active_connections"] = 0
	m["online"] = false
	return m
}

func (u userRow) date() string {
	if !u.ExpiryDate.Valid || u.ExpiryDate.String == "" {
		return ""
	}
	return u.ExpiryDate.String[:10]
}

func (u userRow) lastOnline() any {
	if !u.LastOnline.Valid || u.LastOnline.String == "" {
		return nil
	}
	return strings.Replace(u.LastOnline.String, " ", "T", 1)
}

func (u userRow) tag() any {
	if !u.Tag.Valid || u.Tag.String == "" {
		return nil
	}
	return u.Tag.String
}

func (h *Handler) byUUID(uuidStr string) (userRow, bool) {
	u, err := scanUser(h.Svc.DB.QueryRow(`SELECT `+userCols+` FROM users WHERE uuid = ?`, uuidStr))
	if err != nil {
		return userRow{}, false
	}
	return u, true
}

func userNotFound(w http.ResponseWriter) { auth.WriteDetail(w, http.StatusNotFound, "User not found") }

// --- handlers ---

func (h *Handler) nextUsername(w http.ResponseWriter, r *http.Request) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "No username prefix configured"})
}

// topTraffic is a Phase 3 (billing) placeholder: the shape is registered now so
// the frontend's route list stays stable.
func (h *Handler) topTraffic(w http.ResponseWriter, r *http.Request) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Top traffic users retrieved", Data: []any{}})
}

func (h *Handler) sessions(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.byUUID(r.PathValue("uuid")); !ok {
		userNotFound(w)
		return
	}
	// ponytail: node session diagnostics land with Phase 2.
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User session diagnostics",
		Data: map[string]any{"sessions": []any{}, "active": 0}})
}

func (h *Handler) disconnect(w http.ResponseWriter, r *http.Request) {
	if _, ok := h.byUUID(r.PathValue("uuid")); !ok {
		userNotFound(w)
		return
	}
	// ponytail: node fan-out lands with Phase 2.
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Disconnect command processed",
		Data: map[string]any{}})
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
		if err := h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM users WHERE name LIKE ? ESCAPE '\'`, like).Scan(&total); err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		res, err := h.Svc.DB.Query(`SELECT `+userCols+` FROM users WHERE name LIKE ? ESCAPE '\' ORDER BY id LIMIT ? OFFSET ?`,
			like, pageSize, (page-1)*pageSize)
		if err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		rows = scanAll(res)
	} else {
		res, err := h.Svc.DB.Query(`SELECT ` + userCols + ` FROM users ORDER BY id`)
		if err != nil {
			auth.WriteDetail(w, http.StatusInternalServerError, "Could not list users")
			return
		}
		rows = scanAll(res)
		total = int64(len(rows))
	}

	out := make([]map[string]any, 0, len(rows))
	for _, u := range rows {
		out = append(out, u.live())
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
	if err := h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM users WHERE name = ?`, name).Scan(&exists); err == nil && exists > 0 {
		auth.WriteDetail(w, http.StatusConflict, "User with this name already exists")
		return
	}

	defaults := h.userDefaults()
	if expiry == "" {
		expiry = time.Now().UTC().AddDate(0, 0, defaults.days).Format("2006-01-02")
	}
	maxLogins := defaults.maxUsers
	if req.MaxLogins != nil {
		maxLogins = int(*req.MaxLogins)
	}
	var tag any
	if req.Tag != nil {
		if t := strings.TrimSpace(*req.Tag); t != "" {
			tag = t
		}
	}

	res, err := h.Svc.DB.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, tag)
		 VALUES (?, ?, ?, ?, 0, '{}', ?, ?, 1, ?)`,
		uuid.NewString(), name, req.Total, req.Used, maxLogins, expiry, tag,
	)
	if err != nil {
		auth.WriteDetail(w, http.StatusConflict, "User with this name already exists")
		return
	}
	id, _ := res.LastInsertId()
	row, _ := scanUser(h.Svc.DB.QueryRow(`SELECT `+userCols+` FROM users WHERE id = ?`, id))
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "User created successfully. VPN config will be generated on first download.",
		Data:    row.base(),
	})
}

func (h *Handler) update(w http.ResponseWriter, r *http.Request) {
	uuidStr := r.PathValue("uuid")
	row, ok := h.byUUID(uuidStr)
	if !ok {
		userNotFound(w)
		return
	}
	raw := map[string]json.RawMessage{}
	if !decodeRaw(w, r, &raw) {
		return
	}
	sent := func(key string) bool { _, ok := raw[key]; return ok }

	if sent("expiry_date") {
		if string(raw["expiry_date"]) == "null" {
			auth.WriteDetail(w, http.StatusUnprocessableEntity, "expiry_date cannot be null")
			return
		}
		var s string
		_ = json.Unmarshal(raw["expiry_date"], &s)
		if _, err := time.Parse("2006-01-02", s[:min(10, len(s))]); err != nil {
			auth.WriteValidation(w, "expiry_date", "Input should be a valid date")
			return
		}
	}
	if sent("total") && string(raw["total"]) != "null" {
		var v int64
		_ = json.Unmarshal(raw["total"], &v)
		row.Total = &v
	}
	if sent("total") && string(raw["total"]) == "null" {
		row.Total = nil
	}
	if sent("max_logins") && string(raw["max_logins"]) != "null" {
		var v int64
		_ = json.Unmarshal(raw["max_logins"], &v)
		row.MaxLogins = v
	}
	if sent("tag") {
		var s string
		_ = json.Unmarshal(raw["tag"], &s)
		if t := strings.TrimSpace(s); t != "" {
			row.Tag = sql.NullString{String: t, Valid: true}
		} else {
			row.Tag = sql.NullString{}
		}
	}
	if sent("expiry_date") {
		var s string
		_ = json.Unmarshal(raw["expiry_date"], &s)
		row.ExpiryDate = sql.NullString{String: s[:min(10, len(s))], Valid: true}
	}
	requestedStatus := row.IsActive != 0
	if sent("status") && string(raw["status"]) != "null" {
		var b bool
		_ = json.Unmarshal(raw["status"], &b)
		requestedStatus = b
	}
	row.IsActive = 0
	if requestedStatus && activationBlocked(row) == "" {
		row.IsActive = 1
	}

	if _, err := h.Svc.DB.Exec(
		`UPDATE users SET total = ?, max_logins = ?, expiry_date = ?, is_active = ?, tag = ? WHERE uuid = ?`,
		row.Total, row.MaxLogins, row.ExpiryDate.String, row.IsActive, nullTag(row.Tag), uuidStr,
	); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not update user")
		return
	}
	// ponytail: node status/limit fan-out lands with Phase 2; with zero nodes
	// Python's *_on_all_nodes return true, so success matches.
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User updated successfully"})
}

func (h *Handler) status(w http.ResponseWriter, r *http.Request) {
	uuidStr := r.PathValue("uuid")
	row, ok := h.byUUID(uuidStr)
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
	if _, err := h.Svc.DB.Exec(`UPDATE users SET is_active = ? WHERE uuid = ?`, active, uuidStr); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not change user status")
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Changed user status successfully"})
}

func (h *Handler) resetUsage(w http.ResponseWriter, r *http.Request) {
	uuidStr := r.PathValue("uuid")
	row, ok := h.byUUID(uuidStr)
	if !ok {
		userNotFound(w)
		return
	}
	// Keep the node push hashes; only the counters wipe (crud.reset_user_usage).
	nodeUsage := "{}"
	if parsed := map[string]json.RawMessage{}; json.Unmarshal([]byte(row.NodeUsage), &parsed) == nil {
		if push, ok := parsed["push_hash"]; ok && len(push) > 0 && push[0] == '{' {
			nodeUsage = string(mustJSON(map[string]json.RawMessage{"push_hash": push}))
		}
	}
	if _, err := h.Svc.DB.Exec(`UPDATE users SET used = 0, last_node_usage = 0, node_usage = ? WHERE uuid = ?`, nodeUsage, uuidStr); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not reset usage")
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User usage reset successfully"})
}

func (h *Handler) remove(w http.ResponseWriter, r *http.Request) {
	uuidStr := r.PathValue("uuid")
	row, ok := h.byUUID(uuidStr)
	if !ok {
		userNotFound(w)
		return
	}
	var count int64
	if err := h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&count); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not delete user")
		return
	}
	if count <= 1 {
		auth.WriteDetail(w, http.StatusConflict, "You must keep at least one user — create another before deleting this one")
		return
	}
	h.remember(row)
	if err := h.deleteRow(row); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not delete user")
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User deleted successfully"})
}

// deleteRow is the one shared user-delete path: traffic rows, users row, then
// the node fan-out. A node we cannot reach must not fail the panel-side
// delete: the row is already gone, so log and move on rather than leaving the
// request stuck (no partial-failure state).
func (h *Handler) deleteRow(row userRow) error {
	if _, err := h.Svc.DB.Exec(`DELETE FROM user_traffic_daily WHERE user_id = ?`, row.ID); err != nil {
		return err
	}
	if _, err := h.Svc.DB.Exec(`DELETE FROM users WHERE id = ?`, row.ID); err != nil {
		return err
	}
	if failures, _ := node.DeleteUserOnAllNodes(row.ID, h.Svc.DB)["failed"].([]string); len(failures) > 0 {
		log.Printf("users: user %s deleted panel-side; node fan-out failed on %v", row.Name, failures)
	}
	return nil
}

func (h *Handler) remember(u userRow) {
	h.mu.Lock()
	defer h.mu.Unlock()
	now := time.Now()
	h.deleted[u.UUID] = deletedUser{at: now, snap: u}
	for k, v := range h.deleted {
		if now.Sub(v.at) > deletedTTL {
			delete(h.deleted, k)
		}
	}
	for len(h.deleted) > deletedMax {
		for k := range h.deleted {
			delete(h.deleted, k)
			break
		}
	}
}

func (h *Handler) restore(w http.ResponseWriter, r *http.Request) {
	uuidStr := r.PathValue("uuid")
	h.mu.Lock()
	entry, ok := h.deleted[uuidStr]
	if ok && time.Since(entry.at) > deletedTTL {
		delete(h.deleted, uuidStr)
		ok = false
	}
	h.mu.Unlock()
	if !ok {
		auth.WriteDetail(w, http.StatusGone, "Undo window expired — user can no longer be restored")
		return
	}
	if _, exists := h.byUUID(uuidStr); exists {
		h.mu.Lock()
		delete(h.deleted, uuidStr)
		h.mu.Unlock()
		auth.WriteDetail(w, http.StatusConflict, "User already exists")
		return
	}
	snap := entry.snap
	if _, err := h.Svc.DB.Exec(
		`INSERT INTO users (uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		snap.UUID, snap.Name, snap.Total, snap.Used, snap.LastNodeUsage, nonEmpty(snap.NodeUsage, "{}"),
		snap.MaxLogins, snap.ExpiryDate.String, snap.IsActive,
	); err != nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Restore failed. Check the panel logs for details."})
		return
	}
	h.mu.Lock()
	delete(h.deleted, uuidStr)
	h.mu.Unlock()
	row, _ := h.byUUID(snap.UUID)
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User restored successfully", Data: row.base()})
}

func (h *Handler) extend(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Days  int64 `json:"days"`
		Bytes int64 `json:"bytes"`
	}
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Days == 0 && req.Bytes == 0 {
		auth.WriteDetail(w, http.StatusUnprocessableEntity, "days or bytes must be greater than 0")
		return
	}
	uuidStr := r.PathValue("uuid")
	row, ok := h.byUUID(uuidStr)
	if !ok {
		userNotFound(w)
		return
	}
	if req.Days != 0 {
		base := time.Now().UTC()
		if row.ExpiryDate.Valid && row.ExpiryDate.String != "" {
			if t, err := time.Parse("2006-01-02", row.ExpiryDate.String[:10]); err == nil {
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
	if _, err := h.Svc.DB.Exec(`UPDATE users SET total = ?, expiry_date = ? WHERE uuid = ?`,
		row.Total, row.ExpiryDate.String, uuidStr); err != nil {
		auth.WriteDetail(w, http.StatusInternalServerError, "Could not extend user")
		return
	}
	row, _ = h.byUUID(uuidStr)
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "User updated", Data: row.base()})
}

func (h *Handler) traffic(w http.ResponseWriter, r *http.Request) {
	row, ok := h.byUUID(r.PathValue("uuid"))
	if !ok {
		userNotFound(w)
		return
	}
	total, perNode := aggregateNodeUsage(h.Svc.DB, row)
	// ponytail: per-day series needs Phase 3 billing; shape stays stable.
	auth.WriteJSON(w, http.StatusOK, auth.Response{
		Success: true,
		Msg:     "User traffic history retrieved",
		Data: map[string]any{
			"days":       []any{},
			"used":       deref(row.Used),
			"total_used": total,
			"per_node":   perNode,
			"total":      row.Total,
		},
	})
}

// aggregateNodeUsage mirrors _aggregate_node_usage in routers/users.py.
func aggregateNodeUsage(db *sql.DB, u userRow) (int64, []map[string]any) {
	nodeIDs := map[string]int64{}
	if res, err := db.Query(`SELECT name, id FROM nodes`); err == nil {
		defer res.Close()
		for res.Next() {
			var name string
			var id int64
			if res.Scan(&name, &id) == nil {
				nodeIDs[name] = id
			}
		}
	}
	var usage map[string]json.RawMessage
	if json.Unmarshal([]byte(u.NodeUsage), &usage) != nil {
		usage = nil
	}
	perNode := []map[string]any{}
	var total int64
	for name, raw := range usage {
		var used int64
		var state struct {
			Total int64 `json:"total"`
		}
		if json.Unmarshal(raw, &state) == nil {
			used = state.Total
		} else {
			_ = json.Unmarshal(raw, &used)
		}
		entry := map[string]any{"node_id": nil, "name": name, "used": used}
		if id, ok := nodeIDs[name]; ok {
			entry["node_id"] = id
		}
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
		if u.ExpiryDate.String[:10] < time.Now().UTC().Format("2006-01-02") {
			return "expired"
		}
	}
	if u.Total != nil && *u.Total <= deref(u.Used) {
		return "out of traffic"
	}
	return ""
}

type defaults struct{ days, trafficGB, maxUsers int }

func (h *Handler) userDefaults() defaults {
	d := defaults{days: 30, trafficGB: 100, maxUsers: 1}
	_ = h.Svc.DB.QueryRow(`SELECT default_days, default_traffic_gb, default_max_users FROM settings LIMIT 1`).
		Scan(&d.days, &d.trafficGB, &d.maxUsers)
	if d.days == 0 {
		d.days = 30
	}
	if d.maxUsers == 0 {
		d.maxUsers = 1
	}
	return d
}

// --- small utilities ---

func decodeBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		auth.WriteValidation(w, "body", "JSON decode error")
		return false
	}
	return true
}

func decodeRaw(w http.ResponseWriter, r *http.Request, dst *map[string]json.RawMessage) bool {
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

func nonEmpty(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
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
