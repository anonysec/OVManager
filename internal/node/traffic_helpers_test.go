package node

import (
	"encoding/pem"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"testing"

	"database/sql"

	"github.com/anonysec/OVManager/internal/db"
)

const trafficSchema = `
CREATE TABLE nodes (id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL,
  tunnel_address TEXT, protocol TEXT NOT NULL DEFAULT '', ovpn_port INTEGER NOT NULL DEFAULT 0,
  port INTEGER NOT NULL, key TEXT NOT NULL, status INTEGER NOT NULL DEFAULT 1,
  server_ca TEXT, country_code TEXT, latitude REAL, longitude REAL, extra_ports TEXT DEFAULT '');
CREATE TABLE users (id INTEGER PRIMARY KEY, uuid TEXT, name TEXT NOT NULL, used BIGINT DEFAULT 0, total BIGINT, max_logins INTEGER DEFAULT 1, is_active INTEGER DEFAULT 1, expiry_date TEXT, node_usage TEXT DEFAULT '{}');
`

func newTrafficDB(t *testing.T) *sql.DB {
	t.Helper()
	conn, err := db.Open(filepath.Join(t.TempDir(), "traffic.db"))
	if err != nil {
		t.Fatalf("db.Open: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	if _, err := conn.Exec(trafficSchema); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return conn
}

func seedTrafficNode(t *testing.T, conn *sql.DB, id int64, name string, srv *httptest.Server) {
	t.Helper()
	u, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatalf("parse url: %v", err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatalf("parse port: %v", err)
	}
	pin := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, port, key, status, server_ca) VALUES (?, ?, ?, ?, 'k', 1, ?)`,
		id, name, u.Hostname(), port, pin,
	); err != nil {
		t.Fatalf("insert node: %v", err)
	}
}
