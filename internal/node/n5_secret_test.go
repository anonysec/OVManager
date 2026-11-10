package node

import (
	"database/sql"
	"testing"

	"github.com/anonysec/OVManager/internal/crypto"
	_ "modernc.org/sqlite"
)

func TestScanNodeReturnsErrorOnBadEncryptedKey(t *testing.T) {
	d, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	defer d.Close()
	if _, err := d.Exec(`CREATE TABLE Node (id INTEGER PRIMARY KEY, name TEXT, address TEXT, tunnel_address TEXT, protocol TEXT, ovpn_port INTEGER, port INTEGER, key TEXT, status INTEGER, server_ca TEXT, country_code TEXT, latitude REAL, longitude REAL, extra_ports TEXT)`); err != nil {
		t.Fatal(err)
	}
	if _, err := d.Exec(`INSERT INTO Node (id, name, address, key, status) VALUES (1, 'n', '1.2.3.4', 'enc:v2:AAAA', 1)`); err != nil {
		t.Fatal(err)
	}
	// no valid secret.key -> decryption must fail
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)
	_, err = scanNode(d.QueryRow(`SELECT id, name, address, COALESCE(tunnel_address,''), protocol, ovpn_port, port, COALESCE(key,''), status, server_ca, country_code, latitude, longitude, COALESCE(extra_ports,'') FROM Node WHERE id=1`))
	if err == nil {
		t.Fatal("expected decryption error")
	}
	_ = crypto.EncPrefix
}
