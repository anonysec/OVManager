package panel

import (
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/crypto"
	_ "modernc.org/sqlite"
)

func TestAllNodesDecryptsEncryptedKey(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)

	conn, err := sql.Open("sqlite", filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := conn.Exec(`CREATE TABLE Node (id INTEGER PRIMARY KEY, name VARCHAR, address VARCHAR, tunnel_address VARCHAR, protocol VARCHAR, ovpn_port INTEGER, port INTEGER, key VARCHAR, status BOOLEAN, server_ca VARCHAR, settings TEXT DEFAULT '{}')`); err != nil {
		t.Fatal(err)
	}
	enc, err := crypto.EncryptSecret("node-secret-api-key", dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Exec(`INSERT INTO Node (id, name, address, key, status) VALUES (1, 'n1', '10.0.0.1', ?, 1)`, enc); err != nil {
		t.Fatal(err)
	}

	h := NewHandler(auth.NewService(conn, dir))
	nodes := h.allNodes()
	if len(nodes) != 1 {
		t.Fatalf("got %d nodes, want 1", len(nodes))
	}
	if nodes[0].Key != "node-secret-api-key" {
		t.Fatalf("Key = %q, want decrypted", nodes[0].Key)
	}
}
