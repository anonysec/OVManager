package node

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

const revocationSchema = trafficSchema + `
CREATE TABLE PendingUserRevocation (
  node_id INTEGER NOT NULL, user_id INTEGER NOT NULL, user_uuid TEXT NOT NULL,
  user_name TEXT NOT NULL, created_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (node_id, user_id));
`

func newRevocationDB(t *testing.T) *sql.DB {
	t.Helper()
	conn := newTrafficDB(t)
	if _, err := conn.Exec(revocationSchema); err != nil {
		// trafficSchema tables already exist; create only the jobs table.
		if _, err2 := conn.Exec(`CREATE TABLE PendingUserRevocation (
  node_id INTEGER NOT NULL, user_id INTEGER NOT NULL, user_uuid TEXT NOT NULL,
  user_name TEXT NOT NULL, created_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (node_id, user_id))`); err2 != nil {
			t.Fatalf("jobs schema: %v", err2)
		}
	}
	return conn
}

func seedJob(t *testing.T, conn *sql.DB, nodeID, userID int64) {
	t.Helper()
	if _, err := conn.Exec(`INSERT INTO PendingUserRevocation
		(node_id, user_id, user_uuid, user_name, created_at) VALUES (?, ?, 'uuid', 'alice', 1)`,
		nodeID, userID); err != nil {
		t.Fatalf("seed job: %v", err)
	}
}

func jobCount(t *testing.T, conn *sql.DB, nodeID, userID int64) int {
	t.Helper()
	var n int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM PendingUserRevocation WHERE node_id = ? AND user_id = ?`,
		nodeID, userID).Scan(&n); err != nil {
		t.Fatalf("count jobs: %v", err)
	}
	return n
}

func deleteUserServer(t *testing.T, success bool) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/sync/user/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		body, _ := json.Marshal(map[string]any{"success": success, "msg": "done"})
		_, _ = w.Write(body)
	})
	srv := httptest.NewTLSServer(mux)
	t.Cleanup(srv.Close)
	return srv
}

func TestProcessPendingRevocationsAcksAndRemoves(t *testing.T) {
	conn := newRevocationDB(t)
	srv := deleteUserServer(t, true)
	seedTrafficNode(t, conn, 1, "node-a", srv)
	seedJob(t, conn, 1, 7)
	res := ProcessPendingRevocations(conn, 20)
	if res.Acknowledged != 1 || jobCount(t, conn, 1, 7) != 0 {
		t.Fatalf("ack pass = %+v, jobs left = %d", res, jobCount(t, conn, 1, 7))
	}
}

func TestProcessPendingRevocationsRetainsOnFailure(t *testing.T) {
	conn := newRevocationDB(t)
	srv := deleteUserServer(t, false)
	seedTrafficNode(t, conn, 1, "node-a", srv)
	seedJob(t, conn, 1, 7)
	res := ProcessPendingRevocations(conn, 20)
	if res.Failed != 1 || jobCount(t, conn, 1, 7) != 1 {
		t.Fatalf("failure pass = %+v, jobs left = %d", res, jobCount(t, conn, 1, 7))
	}
	var msg string
	if err := conn.QueryRow(`SELECT last_error FROM PendingUserRevocation WHERE node_id = 1 AND user_id = 7`).Scan(&msg); err != nil {
		t.Fatalf("read last_error: %v", err)
	}
	if msg == "" {
		t.Fatalf("failure message not recorded")
	}
}

func TestProcessPendingRevocationsRetiresJobForDeletedNode(t *testing.T) {
	conn := newRevocationDB(t)
	seedJob(t, conn, 99, 7)
	res := ProcessPendingRevocations(conn, 20)
	if res.Acknowledged != 1 || jobCount(t, conn, 99, 7) != 0 {
		t.Fatalf("missing-node pass = %+v, jobs left = %d", res, jobCount(t, conn, 99, 7))
	}
}

func TestProcessPendingRevocationsRetainsOfflineJob(t *testing.T) {
	conn := newRevocationDB(t)
	// Node row points at a closed port: delivery must fail and retain the job.
	srv := deleteUserServer(t, true)
	seedTrafficNode(t, conn, 1, "node-a", srv)
	srv.Close()
	seedJob(t, conn, 1, 7)
	res := ProcessPendingRevocations(conn, 20)
	if res.Failed != 1 || jobCount(t, conn, 1, 7) != 1 {
		t.Fatalf("offline pass = %+v, jobs left = %d", res, jobCount(t, conn, 1, 7))
	}
}
