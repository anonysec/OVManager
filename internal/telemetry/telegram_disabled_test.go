// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"context"
	"database/sql/driver"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/db"
	_ "modernc.org/sqlite"
)

var selectCounter atomic.Int64

type countingConnector struct{ driver.Connector }

func (c *countingConnector) Connect(ctx context.Context) (driver.Conn, error) {
	conn, err := c.Connector.Connect(ctx)
	return &countingConn{Conn: conn}, err
}

type countingConn struct{ driver.Conn }

func (c *countingConn) QueryContext(ctx context.Context, q string, args []driver.NamedValue) (driver.Rows, error) {
	selectCounter.Add(1)
	qc, ok := c.Conn.(driver.QueryerContext)
	if !ok {
		return nil, errors.New("unsupported")
	}
	return qc.QueryContext(ctx, q, args)
}
func (c *countingConn) ExecerContext() driver.ExecerContext { return c }
func (c *countingConn) ExecContext(ctx context.Context, q string, args []driver.NamedValue) (driver.Result, error) {
	ec, ok := c.Conn.(driver.ExecerContext)
	if !ok {
		return nil, errors.New("unsupported")
	}
	return ec.ExecContext(ctx, q, args)
}
func (c *countingConn) QueryerContext() driver.QueryerContext { return c }
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

func TestBotDisabledRunsZeroSelects(t *testing.T) {
	conn, err := db.Open(t.TempDir() + "/disabled.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, bot_token VARCHAR, bot_enabled BOOLEAN, owner_telegram_id INTEGER)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT OR REPLACE INTO settings (id, bot_token, bot_enabled, owner_telegram_id) VALUES (1, '', 0, 0)`); err != nil {
		t.Fatal(err)
	}
	selectCounter.Store(0)
	ctx, cancel := context.WithCancel(context.Background())
	changed := make(chan struct{})
	_ = changed
	go tgBotLoop(conn, ctx, changed)
	time.Sleep(5 * time.Second)
	cancel()
	if n := selectCounter.Load(); n != 0 {
		t.Fatalf("disabled bot SELECTs in 5s = %d, want 0 after initial read", n)
	}
}
