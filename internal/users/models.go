// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package users

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/internal/auth"
)

type userRow struct {
	ID                     int64
	UUID                   string
	Name                   string
	Total                  *int64
	Used                   *int64
	LastNodeUsage          int64
	NodeUsage              string
	MaxLogins              int64
	ExpiryDate             sql.NullString
	IsActive               int64
	LastOnline             sql.NullString
	LastLoginIP            sql.NullString
	Tag                    sql.NullString
	ActivationTokenHash    sql.NullString
	ActivationTokenExpires sql.NullFloat64
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
	if len(u.ExpiryDate.String) > 10 {
		return u.ExpiryDate.String[:10]
	}
	return u.ExpiryDate.String
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
	ErrKeepLastUser       = errors.New("must keep at least one user")
	ErrUserAlreadyDeleted = errors.New("user already deleted")
)
var (
	errKeepLastUser       = ErrKeepLastUser
	errUserAlreadyDeleted = ErrUserAlreadyDeleted
)

// deleteRow routes through the shared DeleteAccount helper. Node calls only
// happen after the commit; failures are retried by the revocation worker.
func (h *Handler) deleteRow(row userRow, kick bool) ([]string, error) {
	db := h.Svc.DB()
	if _, err := DeleteAccount(db, row.ID, true); err != nil {
		return nil, err
	}
	var failures []string
	if kick {
		_, f := h.kickUserNodes(row)
		failures = append(failures, f...)
	}
	// No synchronous revocation fan-out here: a hanging node would block the
	// HTTP delete for up to 20x120s. The revocation worker delivers the
	// durable pending jobs on the next tick.
	return failures, nil
}

// DeleteResult describes one account deletion and the nodes that still need to
// acknowledge it.
type DeleteResult struct {
	ID               int64
	AccountID        int64
	UserID           int64
	Name             string
	Username         string
	AccountName      string
	UUID             string
	UserUUID         string
	AccountUUID      string
	PendingNodes     []string
	PendingNodeNames []string
	NodeNames        []string
}

// DeleteAccount removes one account and its traffic history in a single
// transaction, enqueuing one pending revocation per registered node. When
// keepOne is true the last remaining account is preserved.
func DeleteAccount(db *sql.DB, userID int64, keepOne bool) (DeleteResult, error) {
	res := DeleteResult{ID: userID, AccountID: userID, UserID: userID}
	if db == nil {
		return res, errors.New("nil database")
	}
	// Read outside the transaction to avoid a shared->exclusive lock upgrade
	// that can deadlock concurrent writers on SQLite.
	var uuid, name string
	if err := db.QueryRow(`SELECT uuid, name FROM users WHERE id = ?`, userID).Scan(&uuid, &name); err != nil {
		if strings.Contains(err.Error(), "no such column") {
			if err2 := db.QueryRow(`SELECT uuid FROM users WHERE id = ?`, userID).Scan(&uuid); err2 != nil {
				if errors.Is(err2, sql.ErrNoRows) {
					return res, errUserAlreadyDeleted
				}
				return res, err2
			}
			name = ""
		} else {
			if errors.Is(err, sql.ErrNoRows) {
				return res, errUserAlreadyDeleted
			}
			return res, err
		}
	}

	// Read the full undo snapshot outside the transaction for the same
	// lock-upgrade reason; the insert still happens inside it.
	snap, _ := scanUser(db.QueryRow(`SELECT id, uuid, name, total, used, last_node_usage, node_usage, max_logins, expiry_date, is_active, last_online, tag, NULL AS last_login_ip FROM users WHERE id = ?`, userID))
	if snap.ID == 0 {
		snap = userRow{ID: userID, UUID: uuid, Name: name}
	}
	// Ensure the undo table exists on partially-migrated fixture DBs;
	// migration already creates it in production.
	_, _ = db.Exec(`CREATE TABLE IF NOT EXISTS deleted_users (uuid TEXT PRIMARY KEY, snap_json TEXT NOT NULL, deleted_at REAL NOT NULL, expires_at REAL NOT NULL)`)

	tx, err := db.Begin()
	if err != nil {
		return res, err
	}
	defer tx.Rollback()
	res.Name = name
	res.Username = name
	res.AccountName = name
	res.UUID = uuid
	res.UserUUID = uuid
	res.AccountUUID = uuid

	snapJSON, err := json.Marshal(snap)
	if err != nil {
		return res, err
	}
	nowSec := time.Now().Unix()
	if _, err := tx.Exec(`INSERT INTO deleted_users (uuid, snap_json, deleted_at, expires_at) VALUES (?, ?, ?, ?)
		ON CONFLICT(uuid) DO UPDATE SET snap_json = ?, deleted_at = ?, expires_at = ?`,
		snap.UUID, string(snapJSON), nowSec, nowSec+deletedTTLSeconds,
		string(snapJSON), nowSec, nowSec+deletedTTLSeconds); err != nil {
		return res, err
	}
	if _, err := tx.Exec(`DELETE FROM deleted_users WHERE expires_at < ?`, nowSec); err != nil {
		return res, err
	}

	if _, err := tx.Exec(`DELETE FROM user_traffic_daily WHERE user_id = ?`, userID); err != nil {
		return res, err
	}
	var stmt string
	if keepOne {
		stmt = `DELETE FROM users WHERE id = ? AND uuid = ? AND (SELECT COUNT(*) FROM users) > 1`
	} else {
		stmt = `DELETE FROM users WHERE id = ? AND uuid = ?`
	}
	r, err := tx.Exec(stmt, userID, uuid)
	if err != nil {
		return res, err
	}
	n, err := r.RowsAffected()
	if err != nil {
		return res, err
	}
	if n == 0 {
		var exists int
		err := tx.QueryRow(`SELECT 1 FROM users WHERE id = ? AND uuid = ?`, userID, uuid).Scan(&exists)
		if errors.Is(err, sql.ErrNoRows) {
			return res, errUserAlreadyDeleted
		}
		if err != nil {
			return res, err
		}
		if keepOne {
			return res, errKeepLastUser
		}
		return res, errUserAlreadyDeleted
	}

	rows, err := tx.Query(`SELECT id, name FROM nodes`)
	if err != nil {
		if strings.Contains(err.Error(), "no such table") {
			rows = nil
		} else {
			return res, err
		}
	}
	type nodeInfo struct {
		id   int64
		name string
	}
	var nodes []nodeInfo
	if rows != nil {
		for rows.Next() {
			var ni nodeInfo
			if err := rows.Scan(&ni.id, &ni.name); err != nil {
				rows.Close()
				return res, err
			}
			nodes = append(nodes, ni)
		}
		rows.Close()
	}

	now := float64(time.Now().Unix())
	// Ensure the pending table exists so deletion is durable even on a
	// partially-migrated or fixture database.
	if _, err := tx.Exec(`CREATE TABLE IF NOT EXISTS pending_user_revocations (
		node_id INTEGER NOT NULL, user_id INTEGER NOT NULL, user_uuid TEXT NOT NULL,
		user_name TEXT NOT NULL, created_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '',
		PRIMARY KEY (node_id, user_id))`); err != nil {
		return res, err
	}
	hasPending := 1
	_ = hasPending
	for _, ni := range nodes {
		if hasPending > 0 {
			if _, err := tx.Exec(`INSERT OR IGNORE INTO pending_user_revocations (node_id, user_id, user_uuid, user_name, created_at, last_error) VALUES (?, ?, ?, ?, ?, '')`, ni.id, userID, uuid, name, now); err != nil {
				return res, err
			}
		}
		res.PendingNodes = append(res.PendingNodes, ni.name)
		res.PendingNodeNames = append(res.PendingNodeNames, ni.name)
		res.NodeNames = append(res.NodeNames, ni.name)
	}

	if err := tx.Commit(); err != nil {
		return res, err
	}
	return res, nil
}
