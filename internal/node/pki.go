// TLS pinning helpers (backend/node/pki.py).
package node

import (
	"crypto/tls"
	"encoding/pem"
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
	dialer := &tls.Dialer{Config: &tls.Config{InsecureSkipVerify: true}} //nolint:gosec // TOFU fetch
	conn, err := dialer.Dial("tcp", address+":"+strconv.Itoa(port))      //nolint:noctx
	if err != nil {
		return ""
	}
	defer conn.Close()
	tconn, ok := conn.(*tls.Conn)
	if !ok {
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

// CAFileFor materializes a pinned CA for nodeID and returns its path. Returns
// ("", false) when there is no pin or the PEM is not a certificate.
func CAFileFor(nodeID int64, serverCA string) (string, bool) {
	if serverCA == "" || !isPEM(serverCA) {
		return "", false
	}
	dir := filepath.Join(DataDir, "node-certs")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", false
	}
	path := filepath.Join(dir, strconv.FormatInt(nodeID, 10)+".pem")
	current, _ := os.ReadFile(path)
	if string(current) != serverCA {
		if err := os.WriteFile(path, []byte(serverCA), 0o600); err != nil {
			return "", false
		}
	}
	return path, true
}
