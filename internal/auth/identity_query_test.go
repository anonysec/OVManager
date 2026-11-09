// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"modernc.org/sqlite"
	_ "modernc.org/sqlite"
)

var queryCount atomic.Int64

type countingConnector struct {
	driver.Connector
}

func (c *countingConnector) Connect(ctx context.Context) (driver.Conn, error) {
	conn, err := c.Connector.Connect(ctx)
	if err != nil {
		return nil, err
	}
	return &countingConn{Conn: conn}, nil
}

type countingConn struct{ driver.Conn }

func (c *countingConn) QueryerContext() driver.QueryerContext { return c }
func (c *countingConn) ExecerContext() driver.ExecerContext   { return c }
func (c *countingConn) QueryContext(ctx context.Context, q string, args []driver.NamedValue) (driver.Rows, error) {
	queryCount.Add(1)
	if qc, ok := c.Conn.(driver.QueryerContext); ok {
		return qc.QueryContext(ctx, q, args)
	}
	vals := make([]driver.Value, len(args))
	for i, a := range args {
		vals[i] = a.Value
	}
	return c.Conn.(driver.Queryer).Query(q, vals)
}
func (c *countingConn) ExecContext(ctx context.Context, q string, args []driver.NamedValue) (driver.Result, error) {
	queryCount.Add(1)
	if ec, ok := c.Conn.(driver.ExecerContext); ok {
		return ec.ExecContext(ctx, q, args)
	}
	vals := make([]driver.Value, len(args))
	for i, a := range args {
		vals[i] = a.Value
	}
	return c.Conn.(driver.Execer).Exec(q, vals)
}
func (c *countingConn) ResetSession(ctx context.Context) error {
	if rs, ok := c.Conn.(driver.SessionResetter); ok {
		return rs.ResetSession(ctx)
	}
	return nil
}
func (c *countingConn) IsValid() bool {
	if v, ok := c.Conn.(driver.Validator); ok {
		return v.IsValid()
	}
	return true
}
func (c *countingConn) BeginTx(ctx context.Context, o driver.TxOptions) (driver.Tx, error) {
	if b, ok := c.Conn.(driver.ConnBeginTx); ok {
		return b.BeginTx(ctx, o)
	}
	return nil, nil
}

func TestIdentityQueryCount(t *testing.T) {
	base, err := sqlite.NewConnector(":memory:")
	if err != nil {
		t.Fatal(err)
	}
	d := sql.OpenDB(&countingConnector{Connector: base})
	t.Cleanup(func() { _ = d.Close() })
	_, err = d.Exec(`
		CREATE TABLE admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, is_owner INTEGER DEFAULT 0);
		CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, token_hash TEXT UNIQUE NOT NULL, username TEXT NOT NULL, role TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL, last_seen_at REAL NOT NULL, user_agent TEXT, ip TEXT);
		CREATE TABLE audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT, promoted BOOLEAN NOT NULL DEFAULT 0);
		CREATE TABLE login_attempts (key_hash TEXT PRIMARY KEY, attempts TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL DEFAULT 0);
	`)
	if err != nil {
		t.Fatal(err)
	}
	seedUser(t, d, "admin", "correct_password_123")
	svc := NewService(d, t.TempDir())
	tok, err := svc.CreateSession("admin", "owner", "", "", 604800)
	if err != nil {
		t.Fatal(err)
	}

	queryCount.Store(0)
	guard := svc.RequireUser(func(w http.ResponseWriter, r *http.Request) {
		if _, ok := svc.CurrentUser(r); !ok {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
	})
	mk := func() *http.Request {
		req := httptest.NewRequest(http.MethodGet, "/api/logs", nil)
		req.Header.Set("Authorization", "Bearer "+tok)
		return req
	}

	w1 := httptest.NewRecorder()
	guard.ServeHTTP(w1, mk())
	if w1.Code != http.StatusOK {
		t.Fatalf("first GET = %d", w1.Code)
	}
	first := queryCount.Load()
	t.Logf("first GET queries=%d", first)

	queryCount.Store(0)
	w2 := httptest.NewRecorder()
	guard.ServeHTTP(w2, mk())
	second := queryCount.Load()
	t.Logf("second GET queries=%d (cache)", second)
	if second != 0 {
		t.Fatalf("cache hit ran %d queries, want 0", second)
	}
	if first > 1 {
		t.Fatalf("fresh identity ran %d queries, want 1", first)
	}
}
