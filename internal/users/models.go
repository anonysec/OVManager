// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package users

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/node"
)

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
	LastLoginIP   sql.NullString
	Tag           sql.NullString
}

const userCols = `id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, last_online, tag, (SELECT ip FROM sessions WHERE username = users.name ORDER BY created_at DESC LIMIT 1) AS last_login_ip`

func scanUser(row interface{ Scan(...any) error }) (userRow, error) {
	var u userRow
	err := row.Scan(&u.ID, &u.UUID, &u.Name, &u.Total, &u.Used, &u.LastNodeUsage, &u.NodeUsage,
		&u.MaxLogins, &u.ExpiryDate, &u.IsActive, &u.LastOnline, &u.Tag, &u.LastLoginIP)
	return u, err
}

// base renders the Users response model (backend).
func (u userRow) base() map[string]any {
	return map[string]any{
		"id":            u.ID,
		"name":          u.Name,
		"is_active":     u.IsActive != 0,
		"total":         u.Total,
		"used":          u.Used,
		"max_logins":    u.MaxLogins,
		"expiry_date":   u.date(),
		"uuid":          u.UUID,
		"last_online":   u.lastOnline(),
		"last_login_ip": u.lastLoginIP(),
		"tag":           u.tag(),
	}
}

// live adds the panel-only connection fields (routers/users.py serialize()),
// read from the live snapshot the telemetry collector keeps.
func (u userRow) live(conns map[string]int) map[string]any {
	m := u.base()
	count := conns[u.Name]
	m["active_connections"] = count
	m["online"] = count > 0
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

func (u userRow) lastLoginIP() any {
	if !u.LastLoginIP.Valid || u.LastLoginIP.String == "" {
		return nil
	}
	return u.LastLoginIP.String
}

func (u userRow) tag() any {
	if !u.Tag.Valid || u.Tag.String == "" {
		return nil
	}
	return u.Tag.String
}

// actor is the username of the authenticated caller, for the audit trail.
func (h *Handler) actor(r *http.Request) string {
	if ident, ok := h.Svc.CurrentUser(r); ok {
		return ident.Username
	}
	return "system"
}

func (h *Handler) byUUID(uuidStr string) (userRow, bool) {
	u, err := scanUser(h.Svc.DB().QueryRow(`SELECT `+userCols+` FROM users WHERE uuid = ?`, uuidStr))
	if err != nil {
		return userRow{}, false
	}
	return u, true
}

func (h *Handler) byID(id int64) (userRow, bool) {
	if id <= 0 {
		return userRow{}, false
	}
	u, err := scanUser(h.Svc.DB().QueryRow(`SELECT `+userCols+` FROM users WHERE id = ?`, id))
	if err != nil {
		return userRow{}, false
	}
	return u, true
}

func parseUserID(raw string) (int64, bool) {
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

// byPathUser keeps the existing UUID form intact while resolving the explicit
// /users/id/{id} aliases to a currently existing row. Numeric IDs are keys for
// live rows, not durable/public identifiers; deleted-user restore stays UUID-based.
func (h *Handler) byPathUser(r *http.Request) (userRow, bool) {
	if rawID := r.PathValue("id"); rawID != "" {
		id, ok := parseUserID(rawID)
		if !ok {
			return userRow{}, false
		}
		return h.byID(id)
	}
	return h.byUUID(r.PathValue("uuid"))
}

func userNotFound(w http.ResponseWriter) { auth.WriteDetail(w, http.StatusNotFound, "User not found") }

var (
	errKeepLastUser       = errors.New("must keep at least one user")
	errUserAlreadyDeleted = errors.New("user already deleted")
)

// deleteRow atomically enforces the keep-one rule and removes traffic history.
// The guarded DELETE is itself a write, so SQLite serializes competing deletes
// before evaluating the count. Node calls only happen after the commit.
func (h *Handler) deleteRow(row userRow, kick bool) ([]string, error) {
	db := h.Svc.DB()
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()
	// Delete dependent history first for databases with foreign keys. The
	// transaction acquires the write lock here and rolls this back if the
	// subsequent keep-one check rejects the user deletion.
	if _, err := tx.Exec(`DELETE FROM user_traffic_daily WHERE user_id = ?`, row.ID); err != nil {
		return nil, err
	}
	res, err := tx.Exec(`DELETE FROM users WHERE id = ? AND uuid = ? AND (SELECT COUNT(*) FROM users) > 1`, row.ID, row.UUID)
	if err != nil {
		return nil, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return nil, err
	}
	if n == 0 {
		var exists int
		err := tx.QueryRow(`SELECT 1 FROM users WHERE id = ? AND uuid = ?`, row.ID, row.UUID).Scan(&exists)
		if errors.Is(err, sql.ErrNoRows) {
			return nil, errUserAlreadyDeleted
		}
		if err != nil {
			return nil, err
		}
		return nil, errKeepLastUser
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}

	var failures []string
	if kick {
		_, failures = h.kickUserNodes(row)
	}
	if failed, _ := node.DeleteUserOnAllNodes(row.ID, db)["failed"].([]string); len(failed) > 0 {
		log.Printf("users: user %s deleted panel-side; node fan-out failed on %v", row.Name, failed)
		failures = append(failures, failed...)
	}
	return failures, nil
}

// remember stores a deleted user snapshot for undo.
func (h *Handler) remember(u userRow) error {
	snapJSON, err := json.Marshal(u)
	if err != nil {
		return err
	}
	now := time.Now().Unix()
	expiresAt := now + deletedTTLSeconds
	_, err = h.Svc.DB().Exec(
		`INSERT INTO deleted_users (uuid, snap_json, deleted_at, expires_at) VALUES (?, ?, ?, ?)
		 ON CONFLICT(uuid) DO UPDATE SET snap_json = ?, deleted_at = ?, expires_at = ?`,
		u.UUID, string(snapJSON), now, expiresAt,
		string(snapJSON), now, expiresAt,
	)
	if err != nil {
		return err
	}
	// Prune expired entries (best effort)
	_, _ = h.Svc.DB().Exec(`DELETE FROM deleted_users WHERE expires_at < ?`, now)
	return nil
}
