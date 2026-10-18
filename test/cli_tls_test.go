// Parity tests for `ovm tls`: the terminal-side self-signed issuance writes a
// parseable pair into the DATA_DIR, and a bad input path fails without
// touching anything.
package tests

import (
	"bytes"
	"crypto/x509"
	"encoding/pem"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/cli"
)

// TestCLITLSSelfSigned: a happy-path selfsigned run must install a real
// certificate pair under DATA_DIR/tls and report success.
func TestCLITLSSelfSigned(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	var out bytes.Buffer
	code := cli.Run([]string{"tls", "selfsigned", "example.com", "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 0 {
		t.Fatalf("exit = %d, want 0\n%s", code, out.String())
	}
	if !strings.Contains(out.String(), "issued for example.com") {
		t.Errorf("output missing success line:\n%s", out.String())
	}
	certPath := filepath.Join(dataDir, "tls", "fullchain.pem")
	keyPath := filepath.Join(dataDir, "tls", "privkey.pem")
	raw, err := os.ReadFile(certPath)
	if err != nil {
		t.Fatalf("cert not written: %v", err)
	}
	block, _ := pem.Decode(raw)
	if block == nil || block.Type != "CERTIFICATE" {
		t.Fatalf("cert is not PEM CERTIFICATE data")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatalf("cert does not parse: %v", err)
	}
	if len(cert.DNSNames) != 1 || cert.DNSNames[0] != "example.com" {
		t.Errorf("SANs = %v, want [example.com]", cert.DNSNames)
	}
	if !cert.NotAfter.After(time.Now()) {
		t.Errorf("cert already expired: %v", cert.NotAfter)
	}
	key, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatalf("key not written: %v", err)
	}
	if block, _ := pem.Decode(key); block == nil || block.Type != "PRIVATE KEY" {
		t.Fatalf("key is not PEM PRIVATE KEY data")
	}
	if info, err := os.Stat(keyPath); err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("key mode = %v err=%v, want 0600", info.Mode().Perm(), err)
	}
}

// TestCLITLSInstallBadPairPath: a missing cert path must fail cleanly (exit 1)
// and write nothing.
func TestCLITLSInstallBadPairPath(t *testing.T) {
	installDir, dataDir := cliFixture(t)
	var out bytes.Buffer
	missing := filepath.Join(t.TempDir(), "no-such-cert.pem")
	code := cli.Run([]string{"tls", "install", missing, missing, "--install-dir", installDir, "--data-dir", dataDir}, &out)
	if code != 1 {
		t.Fatalf("exit = %d, want 1\n%s", code, out.String())
	}
	if !strings.Contains(out.String(), "could not read cert") {
		t.Errorf("output missing read failure:\n%s", out.String())
	}
	if _, err := os.Stat(filepath.Join(dataDir, "tls")); !os.IsNotExist(err) {
		t.Errorf("tls dir created despite failure")
	}
}
