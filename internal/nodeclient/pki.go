// TLS pinning helpers (backend/node/pki.py).
package nodeclient

import (
	"crypto/tls"
	"encoding/pem"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// DataDir is where materialized pin files live. DATA_DIR overrides at call
// sites (main.go); the default matches backend/data_paths.py.
var DataDir = defaultDataDir()

func defaultDataDir() string {
	if d := os.Getenv("DATA_DIR"); d != "" {
		return d
	}
	return filepath.Join("data")
}

// FetchServerCert fetches the TLS certificate PEM served by address:port.
// Verification is intentionally off (trust-on-first-use fetch). Returns "" on
// any failure.
func FetchServerCert(address string, port int, timeout time.Duration) string {
	if timeout == 0 {
		timeout = 10 * time.Second
	}
	target := net.JoinHostPort(address, strconv.Itoa(port))
	nd := &net.Dialer{Timeout: timeout}
	rawConn, err := nd.Dial("tcp", target)
	if err != nil {
		return ""
	}
	// Honour the timeout for the TLS handshake too: a listener that accepts
	// TCP but never completes the handshake must not block indefinitely.
	rawConn.SetDeadline(time.Now().Add(timeout))
	defer rawConn.Close()
	tconn := tls.Client(rawConn, &tls.Config{InsecureSkipVerify: true}) //nolint:gosec // TOFU fetch
	if err := tconn.Handshake(); err != nil {
		return ""
	}
	certs := tconn.ConnectionState().PeerCertificates
	if len(certs) == 0 {
		return ""
	}
	pemText := string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certs[0].Raw}))
	if !strings.Contains(pemText, "BEGIN CERTIFICATE") {
		return ""
	}
	return pemText
}
