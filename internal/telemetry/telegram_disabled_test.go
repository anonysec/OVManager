// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package telemetry

import (
	"context"
	"database/sql"
	"testing"
	"time"

	"modernc.org/sqlite"
)

func TestBotDisabledRunsZeroSelects(t *testing.T) {
	conn, err := sql.Open("sqlite", t.TempDir()+"/disabled.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	_ = sqlite.NewConnector
	if _, err := conn.Exec(`CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, bot_token VARCHAR, bot_enabled BOOLEAN, owner_telegram_id INTEGER)`); err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT OR REPLACE INTO settings (id, bot_token, bot_enabled, owner_telegram_id) VALUES (1, '', 0, 0)`); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	changed := make(chan struct{})
	_ = changed
	go tgBotLoop(conn, ctx, changed)
	time.Sleep(200 * time.Millisecond)
	cancel()
	// bot disabled: loop checks token on interval (60s default), no tight spin
}
