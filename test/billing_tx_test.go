// Billing transaction capability: ApplyUserTraffic's user write and its daily
// row must roll back together when they share an Execer (*sql.Tx).
package tests

import (
	"testing"

	"github.com/anonysec/OVManager/go/internal/billing"
)

func TestApplyUserTrafficRollsBackUserAndDailyTogether(t *testing.T) {
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name, used, node_usage) VALUES (1,'u1','ann',100,'{}')`); err != nil {
		t.Fatalf("seed user: %v", err)
	}

	tx, err := conn.Begin()
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if !billing.ApplyUserTraffic(tx, 1, 100, "{}", 150, `{"1":150}`, 50) {
		t.Fatalf("ApplyUserTraffic on tx = false, want true")
	}
	// Force a failure inside the tx, then roll back: both writes must vanish.
	if _, err := tx.Exec(`INSERT INTO users (id, uuid, name) VALUES (1,'dup','dup')`); err == nil {
		t.Fatalf("conflicting insert unexpectedly succeeded")
	}
	if err := tx.Rollback(); err != nil {
		t.Fatalf("rollback: %v", err)
	}

	var used int64
	var state string
	if err := conn.QueryRow(`SELECT used, node_usage FROM users WHERE id = 1`).Scan(&used, &state); err != nil {
		t.Fatalf("read user: %v", err)
	}
	if used != 100 || state != "{}" {
		t.Fatalf("after rollback used=%d state=%q, want 100 and {}", used, state)
	}
	var daily int64
	if err := conn.QueryRow(`SELECT COUNT(*) FROM user_traffic_daily WHERE user_id = 1`).Scan(&daily); err != nil {
		t.Fatalf("read daily: %v", err)
	}
	if daily != 0 {
		t.Fatalf("daily rows after rollback = %d, want 0", daily)
	}
}

func TestApplyUserTrafficCommitsWithTx(t *testing.T) {
	conn, _ := newTestDB(t)
	if _, err := conn.Exec(extraTelemetryDDL); err != nil {
		t.Fatalf("schema: %v", err)
	}
	if _, err := conn.Exec(`INSERT INTO users (id, uuid, name, used, node_usage) VALUES (1,'u1','ann',100,'{}')`); err != nil {
		t.Fatalf("seed user: %v", err)
	}

	tx, err := conn.Begin()
	if err != nil {
		t.Fatalf("begin: %v", err)
	}
	if !billing.ApplyUserTraffic(tx, 1, 100, "{}", 150, `{"1":150}`, 50) {
		t.Fatalf("ApplyUserTraffic = false, want true")
	}
	if err := tx.Commit(); err != nil {
		t.Fatalf("commit: %v", err)
	}

	var used int64
	var bytes int64
	if err := conn.QueryRow(`SELECT used FROM users WHERE id = 1`).Scan(&used); err != nil {
		t.Fatalf("read user: %v", err)
	}
	if err := conn.QueryRow(`SELECT bytes FROM user_traffic_daily WHERE user_id = 1`).Scan(&bytes); err != nil {
		t.Fatalf("read daily: %v", err)
	}
	if used != 150 || bytes != 50 {
		t.Fatalf("after commit used=%d daily=%d, want 150 and 50", used, bytes)
	}
}
