// Certificate parsing helpers that remain on the live path.
// The managed-pair pipeline (validate, atomic replace, previous-pair
// retention, upload/generate/renew/rollback) was removed; TLS certs now
// arrive externally via `ovmanager tls install` and the panel only reads
// them at startup. isoFormat and resolvePath stay for maintenance.go.
package panel

import (
	"crypto/x509"
	"encoding/pem"
	"errors"
	"path/filepath"
	"time"
)

func parseCertificatePEM(raw []byte) (*x509.Certificate, error) {
	for {
		block, rest := pem.Decode(raw)
		if block == nil {
			return nil, errors.New("the certificate file is not a valid PEM certificate")
		}
		if block.Type == "CERTIFICATE" {
			return x509.ParseCertificate(block.Bytes)
		}
		raw = rest
	}
}

func resolvePath(path string) string {
	abs, err := filepath.Abs(path)
	if err != nil {
		return filepath.Clean(path)
	}
	dir, base := filepath.Split(abs)
	if real, err := filepath.EvalSymlinks(filepath.Clean(dir)); err == nil {
		return filepath.Join(real, base)
	}
	return filepath.Clean(abs)
}

func isoFormat(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05.999999-07:00")
}
