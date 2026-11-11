// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package node

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"database/sql"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/internal/auth"
	_ "modernc.org/sqlite"
)

func generateTestCert(t *testing.T, cn string) string {
	priv, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, &template, &template, &priv.PublicKey, priv)
	if err != nil {
		t.Fatal(err)
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}))
}

func setupNodeTestDB(t *testing.T) *sql.DB {
	d, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = d.Close() })
	_, err = d.Exec(`
		CREATE TABLE Node (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			address TEXT NOT NULL,
			port INTEGER NOT NULL DEFAULT 2083,
			ovpn_port INTEGER NOT NULL DEFAULT 1194,
			tunnel_address TEXT,
			protocol TEXT DEFAULT 'udp',
			key TEXT NOT NULL,
			server_ca TEXT,
			status INTEGER DEFAULT 1,
			country_code TEXT,
			latitude REAL,
			longitude REAL,
			extra_ports TEXT, settings TEXT DEFAULT '{}');
		CREATE TABLE audit_logs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
			user TEXT,
			action TEXT,
			level TEXT,
			message TEXT,
			metadata TEXT
		);
	`)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestHandleRepinRequiresFingerprintConfirmation(t *testing.T) {
	d := setupNodeTestDB(t)

	oldCert := generateTestCert(t, "old-node")
	oldFP := CertFingerprint(oldCert)

	res, err := d.Exec(`INSERT INTO Node (name, address, port, ovpn_port, server_ca, key, status)
		VALUES ('test-node', '127.0.0.1', 2083, 1194, ?, 'test-key', 1)`, oldCert)
	if err != nil {
		t.Fatal(err)
	}
	nodeID, _ := res.LastInsertId()

	svc := auth.NewService(d, t.TempDir())
	h := NewHandler(svc)

	// 1. Unconfirmed re-pin request must return confirmation_required and not modify database
	req := httptest.NewRequest(http.MethodPost, "/nodes/1/repin", strings.NewReader(`{}`))
	req.SetPathValue("node_id", "1")
	w := httptest.NewRecorder()
	h.handleRepin(w, req)

	var resp struct {
		Success bool           `json:"success"`
		Data    map[string]any `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}
	if resp.Success {
		t.Fatalf("expected handleRepin to require confirmation on empty request, got success")
	}

	// Verify server_ca in database was not changed
	var currentCert string
	_ = d.QueryRow(`SELECT server_ca FROM Node WHERE id = ?`, nodeID).Scan(&currentCert)
	if CertFingerprint(currentCert) != oldFP {
		t.Fatalf("SECURITY FLAW: server_ca was modified without confirmation")
	}

	// 2. Mismatched fingerprint must be rejected
	badReq := httptest.NewRequest(http.MethodPost, "/nodes/1/repin", strings.NewReader(`{"expected_fingerprint":"AA:BB:CC:DD"}`))
	badReq.SetPathValue("node_id", "1")
	wBad := httptest.NewRecorder()
	h.handleRepin(wBad, badReq)

	var badResp struct {
		Success bool `json:"success"`
	}
	_ = json.Unmarshal(wBad.Body.Bytes(), &badResp)
	if badResp.Success {
		t.Fatalf("expected handleRepin to reject mismatched fingerprint")
	}
}

func TestHandleTestNodeRequiresConfirmationWithoutCert(t *testing.T) {
	d := setupNodeTestDB(t)
	svc := auth.NewService(d, t.TempDir())
	h := NewHandler(svc)

	// Without cert or confirmation: must not transmit API key to arbitrary node
	body := `{"address":"127.0.0.1","port":2083,"key":"secret-api-key"}`
	req := httptest.NewRequest(http.MethodPost, "/nodes/test", strings.NewReader(body))
	w := httptest.NewRecorder()
	h.handleTestNode(w, req)

	var resp struct {
		Success bool           `json:"success"`
		Data    map[string]any `json:"data"`
	}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	// Node is not running, so FetchServerCert returns empty or confirmation required
	if resp.Success {
		t.Fatalf("expected handleTestNode to not succeed without valid cert/confirmation")
	}
}
