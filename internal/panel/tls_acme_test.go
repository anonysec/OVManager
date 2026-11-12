// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package panel

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func testPair(t *testing.T, notBefore, notAfter time.Time, dns []string, ips []net.IP) ([]byte, []byte) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: "panel.example"},
		NotBefore:    notBefore,
		NotAfter:     notAfter,
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     dns,
		IPAddresses:  ips,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}),
		pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func TestACMEWindowFollowsLifetime(t *testing.T) {
	now := time.Now()
	tests := []struct {
		name string
		life time.Duration
		want time.Duration
	}{
		{"90 days", 90 * 24 * time.Hour, 30 * 24 * time.Hour},
		{"6 days", 6 * 24 * time.Hour, 2 * 24 * time.Hour},
		{"2 days", 2 * 24 * time.Hour, 24 * time.Hour},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, certPEM := testPair(t, now.Add(-time.Hour), now.Add(tt.life), nil, nil)
			cert, err := parseCertificatePEM(certPEM)
			if err != nil {
				t.Fatal(err)
			}
			got := acmeRenewWindow(cert)
			if diff := got - tt.want; diff < -2*time.Hour || diff > 2*time.Hour {
				t.Fatalf("window = %s, want %s", got, tt.want)
			}
		})
	}
}

func TestACMETargetPrefersDNSThenIP(t *testing.T) {
	now := time.Now()
	_, certPEM := testPair(t, now.Add(-time.Hour), now.Add(time.Hour), []string{"panel.example"}, nil)
	cert, _ := parseCertificatePEM(certPEM)
	if got := acmeTarget(cert); got != "panel.example" {
		t.Fatalf("target = %q", got)
	}
	_, certPEM = testPair(t, now.Add(-time.Hour), now.Add(time.Hour), nil, []net.IP{net.ParseIP("203.0.113.9")})
	cert, _ = parseCertificatePEM(certPEM)
	if got := acmeTarget(cert); got != "203.0.113.9" {
		t.Fatalf("target = %q", got)
	}
}

func TestWriteManagedFilesActivatesAndRetainsPrevious(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	now := time.Now()
	keyPEM, certPEM := testPair(t, now.Add(-time.Hour), now.Add(90*24*time.Hour), []string{"panel.example"}, nil)
	if _, err := writeManagedFiles(keyPEM, certPEM, "lets-encrypt"); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{sslCertPath(), sslKeyPath()} {
		if _, err := os.Stat(p); err != nil {
			t.Fatalf("%s was not written: %v", p, err)
		}
	}
	if _, err := os.Stat(previousCertPath()); err == nil {
		t.Fatal("the first activation must not create a previous pair")
	}
	keyPEM2, certPEM2 := testPair(t, now.Add(-time.Hour), now.Add(90*24*time.Hour), []string{"panel.example"}, nil)
	if _, err := writeManagedFiles(keyPEM2, certPEM2, "lets-encrypt"); err != nil {
		t.Fatal(err)
	}
	prev, err := os.ReadFile(previousCertPath())
	if err != nil || string(prev) != string(certPEM) {
		t.Fatalf("previous pair was not retained: %v", err)
	}
}

func TestWriteManagedFilesRejectsMismatchedKeyWithoutWriting(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	now := time.Now()
	keyPEM, certPEM := testPair(t, now.Add(-time.Hour), now.Add(90*24*time.Hour), []string{"panel.example"}, nil)
	otherKey, _ := testPair(t, now.Add(-time.Hour), now.Add(90*24*time.Hour), []string{"panel.example"}, nil)
	if _, err := writeManagedFiles(otherKey, certPEM, "test"); err == nil {
		t.Fatal("a key that does not match the certificate must be rejected")
	}
	if _, err := os.Stat(sslCertPath()); err == nil {
		t.Fatal("a rejected pair must write nothing")
	}
	if _, err := writeManagedFiles(keyPEM, certPEM, "test"); err != nil {
		t.Fatal(err)
	}
	before, _ := os.ReadFile(sslCertPath())
	if _, err := writeManagedFiles(otherKey, certPEM, "test"); err == nil {
		t.Fatal("a mismatched replacement must be rejected")
	}
	after, _ := os.ReadFile(sslCertPath())
	if string(before) != string(after) {
		t.Fatal("a rejected replacement must leave the active pair untouched")
	}
}

func TestAtomicWriteRefusesOutsideTLS(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	outside := filepath.Join(t.TempDir(), "escape.pem")
	if err := atomicWrite(outside, []byte("x"), 0o600); err == nil {
		t.Fatal("writing outside DATA_DIR/tls must be refused")
	}
}

func TestACMETickSkipsFreshCertificate(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	saveACMEEnrollment("panel.example")
	now := time.Now()
	_, certPEM := testPair(t, now.Add(-time.Hour), now.Add(90*24*time.Hour), []string{"panel.example"}, nil)
	if err := os.MkdirAll(filepath.Dir(sslCertPath()), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(sslCertPath(), certPEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if !(&Handler{}).acmeTick(context.Background()) {
		t.Fatal("a certificate outside the renewal window must not trigger an issuance")
	}
}

func TestACMETickIgnoresUnenrolledCertificate(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	now := time.Now()
	_, certPEM := testPair(t, now.Add(-time.Hour), now.Add(8*24*time.Hour), []string{"panel.example"}, nil)
	if err := os.MkdirAll(filepath.Dir(sslCertPath()), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(sslCertPath(), certPEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if !(&Handler{}).acmeTick(context.Background()) {
		t.Fatal("an unenrolled certificate (custom/self-signed) must not be renewed")
	}
}

func TestACMETickIgnoresMismatchedEnrollment(t *testing.T) {
	t.Setenv("DataDir", t.TempDir())
	saveACMEEnrollment("other.example")
	now := time.Now()
	_, certPEM := testPair(t, now.Add(-time.Hour), now.Add(8*24*time.Hour), []string{"panel.example"}, nil)
	if err := os.MkdirAll(filepath.Dir(sslCertPath()), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(sslCertPath(), certPEM, 0o644); err != nil {
		t.Fatal(err)
	}
	if !(&Handler{}).acmeTick(context.Background()) {
		t.Fatal("a pair that does not match the enrolled target must not be replaced")
	}
}
