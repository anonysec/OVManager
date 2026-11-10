package node

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

var policySyncLock sync.Mutex

func AccessBlocked(expiryDate string, total *int64, used int64, now time.Time) string {
	if expiryDate != "" {
		date := expiryDate
		if len(date) > 10 {
			date = date[:10]
		}
		if date < now.UTC().Format("2006-01-02") {
			return "expired"
		}
	}
	if total != nil && *total <= used {
		return "out of traffic"
	}
	return ""
}

func (c *Client) ApplyUserPolicy(uid, name string, maxLogins int, active bool) bool {
	status := "deactivate"
	if active {
		status = "activate"
	}
	_, err := do[emptyResponse](c, http.MethodPut, "/sync/user", map[string]any{
		"id": uid, "name": name, "max_logins": maxLogins, "status": status,
	}, reqOpts{timeout: Timeout})
	return err == nil
}

type PolicySyncResult struct {
	Total    int
	Applied  int
	Skipped  int
	Failed   int
	Failures []string
	Results  []any
}

type policyUser struct {
	id        int64
	name      string
	maxLogins int
	isActive  bool
	total     *int64
	used      int64
	expiry    string
	nodeUsage string
}

func loadPolicyUsers(db *sql.DB, userID int64) []policyUser {
	q := `SELECT id, name, COALESCE(max_logins,0), is_active, total, used, COALESCE(expiry_date,''), COALESCE(node_usage,'{}') FROM User`
	args := []any{}
	if userID > 0 {
		q += ` WHERE id = ?`
		args = append(args, userID)
	}
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []policyUser
	for rows.Next() {
		var u policyUser
		var total sql.NullInt64
		var used sql.NullInt64
		var active int64
		if err := rows.Scan(&u.id, &u.name, &u.maxLogins, &active, &total, &used, &u.expiry, &u.nodeUsage); err != nil {
			continue
		}
		u.isActive = active != 0
		if total.Valid {
			v := total.Int64
			u.total = &v
		}
		if used.Valid {
			u.used = used.Int64
		}
		out = append(out, u)
	}
	if err := rows.Err(); err != nil {
		return nil
	}
	return out
}

func policyPushHash(uid string, name string, maxLogins int, active bool) string {
	activeStr := "0"
	if active {
		activeStr = "1"
	}
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%d|%s", uid, name, maxLogins, activeStr)))
	return hex.EncodeToString(sum[:])
}

// Need reconcile implementation. We'll implement generic with filter param via separate functions.
func SyncUserPolicy(db *sql.DB, userID int64, now time.Time) PolicySyncResult {
	return reconcilePolicyUsers(db, userID, now, true)
}

func ReconcileUserPolicies(db *sql.DB, now time.Time, force bool) PolicySyncResult {
	return reconcilePolicyUsers(db, 0, now, force)
}

func reconcilePolicyUsers(db *sql.DB, userID int64, now time.Time, force bool) (res PolicySyncResult) {
	res = PolicySyncResult{Failures: []string{}, Results: []any{}}
	defer func() {
	}()
	if db == nil {
		return res
	}
	policySyncLock.Lock()
	defer policySyncLock.Unlock()

	// Load fresh rows after entering boundary.
	allUsers := loadPolicyUsers(db, 0)
	var users []policyUser
	if userID > 0 {
		for _, u := range allUsers {
			if u.id == userID {
				users = append(users, u)
			}
		}
	} else {
		users = allUsers
	}
	if len(users) == 0 {
		return res
	}
	nodes := getActiveNodes(db)
	if len(nodes) == 0 {
		res.Total = len(users) * 0
		return res
	}

	type job struct {
		node            *Node
		user            policyUser
		desiredHash     string
		effectiveActive bool
	}
	var jobs []job
	skipped := 0
	for _, n := range nodes {
		for _, u := range users {
			effective := u.isActive && AccessBlocked(u.expiry, u.total, u.used, now) == ""
			h := policyPushHash(strconv.FormatInt(u.id, 10), u.name, u.maxLogins, effective)
			if !force && storedPushHashes(u.nodeUsage)[strconv.FormatInt(n.ID, 10)] == h {
				skipped++
				continue
			}
			jobs = append(jobs, job{node: n, user: u, desiredHash: h, effectiveActive: effective})
		}
	}

	res.Total = len(users) * len(nodes)
	res.Skipped = skipped

	if len(jobs) == 0 {
		return res
	}

	pid := PanelIDFor(db)
	// Fan out in chunks of at most NodeFanoutLimit jobs: with more jobs than
	// the semaphore cap, semaphore-queued calls are guaranteed to miss a
	// single shared deadline even when healthy, and the same first chunk
	// would starve the rest on every pass. Per-chunk deadlines let every
	// job start immediately under its own request timeout.
	var raw []any
	for start := 0; start < len(jobs); start += NodeFanoutLimit {
		end := start + NodeFanoutLimit
		if end > len(jobs) {
			end = len(jobs)
		}
		chunk := jobs[start:end]
		calls := make([]func() any, 0, len(chunk))
		for _, j := range chunk {
			j := j
			calls = append(calls, func() any {
				c := NodeClient(j.node, pid)
				return c.ApplyUserPolicy(strconv.FormatInt(j.user.id, 10), j.user.name, j.user.maxLogins, j.effectiveActive)
			})
		}
		raw = append(raw, GatherNodes(calls, RequestFanoutDeadline)...)
	}

	fresh := map[int64]map[string]string{}
	for i, item := range raw {
		j := jobs[i]
		ok := false
		if b, ok2 := item.(bool); ok2 {
			ok = b
		}
		if err, ok2 := item.(error); ok2 {
			res.Failed++
			res.Failures = append(res.Failures, fmt.Sprintf("node=%s user=%d: %v", j.node.Name, j.user.id, err))
			continue
		}
		if !ok {
			res.Failed++
			res.Failures = append(res.Failures, fmt.Sprintf("node=%s user=%d", j.node.Name, j.user.id))
			continue
		}
		res.Applied++
		uid := j.user.id
		if fresh[uid] == nil {
			fresh[uid] = map[string]string{}
		}
		fresh[uid][strconv.FormatInt(j.node.ID, 10)] = j.desiredHash
	}

	// Conditional merges preserving traffic/epoch updates.
	for uid, hashes := range fresh {
		var oldState string
		if err := db.QueryRow(`SELECT COALESCE(node_usage,'{}') FROM User WHERE id = ?`, uid).Scan(&oldState); err != nil {
			continue
		}
		var data map[string]any
		dec := json.NewDecoder(strings.NewReader(oldState))
		dec.UseNumber()
		if err := dec.Decode(&data); err != nil {
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
		canonical, _ := json.Marshal(data)
		_, _ = db.Exec(
			`UPDATE User SET node_usage = ? WHERE id = ? AND COALESCE(node_usage,'{}') = ?`,
			string(canonical), uid, oldState,
		)
	}

	res.Results = []any{}
	return res
}
