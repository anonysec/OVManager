// Certificate lifecycle. The managed-pair pipeline: validate, atomic replace,
// retain the previous pair. Plus the parsing/validation helpers behind it, the
// upload endpoint, self-signed generation, the single-issuance renew endpoint
// (POST /tls/renew, POST /https/automatic) and rollback.
package panel

import (
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Panel-side TLS certificate management (backend).
const (
	maxTLSFileSize = 1024 * 1024
	restartHint    = "Restart the panel to use the new certificate: " +
		"'systemctl restart ovmanager' on a native install, or 'docker restart ovmanager' for Docker."
)

// validation.py's domain rule (a single label is legal) and email rule.
var (
	acmeDomainRe = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?` +
		`(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$`)
	emailRe = regexp.MustCompile(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
)

func validateDomain(value string) bool {
	if value == "" || len(value) > 253 {
		return false
	}
	return acmeDomainRe.MatchString(value)
}

// --- paths ---

func tlsDir() string           { return filepath.Join(dataDir(), "tls") }
func metaPath() string         { return filepath.Join(tlsDir(), "meta.json") }
func previousKeyPath() string  { return filepath.Join(tlsDir(), "previous-privkey.pem") }
func previousCertPath() string { return filepath.Join(tlsDir(), "previous-fullchain.pem") }

// resolvePath is Path.resolve() for a path that may not exist yet.
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

// certWriteMu serializes the pipeline below, like _CERTIFICATE_LOCK did.
var certWriteMu sync.Mutex

// atomicWrite writes data beside its target then replaces it atomically. Only
// paths this module owns (the declared pair, or bookkeeping in DATA_DIR/tls)
// are allowed, checked on the resolved path so a symlink cannot redirect it.
func atomicWrite(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { // #nosec G301 // triaged intentional
		return err
	}
	resolved := resolvePath(path)
	state := resolvePath(tlsDir())
	allowed := map[string]bool{resolvePath(sslKeyPath()): true, resolvePath(sslCertPath()): true}
	if filepath.Dir(resolved) != state && resolved != state && !allowed[resolved] {
		return fmt.Errorf("refusing to write outside the declared certificate paths: %s", resolved)
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), "."+filepath.Base(path)+".*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer func() { _ = os.Remove(name) }()
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	return nil
}

func writeMeta(mode string) {
	meta, err := json.MarshalIndent(map[string]any{
		"mode":       mode,
		"updated_at": time.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00"),
	}, "", "  ")
	if err != nil {
		return
	}
	// Best-effort: a metadata failure must not fail the install.
	_ = atomicWrite(metaPath(), append(meta, '\n'), 0o644)
}

// writeManagedFiles validates and transactionally activates a certificate pair,
// restoring the previous one if any write fails. Returns the parsed cert.
func writeManagedFiles(keyPEM, certPEM []byte, mode string) (*x509.Certificate, error) {
	if _, cert, err := validatePair(keyPEM, certPEM); err != nil {
		return nil, err
	} else if cert == nil {
		return nil, errors.New("the certificate file is not a valid PEM certificate.")
	}
	certWriteMu.Lock()
	defer certWriteMu.Unlock()
	if err := os.MkdirAll(tlsDir(), 0o755); err != nil { // #nosec G301 // triaged intentional
		return nil, err
	}
	var oldKey, oldCert, oldMeta []byte
	if fileExists(sslKeyPath()) {
		oldKey, _ = os.ReadFile(sslKeyPath())
	}
	if fileExists(sslCertPath()) {
		oldCert, _ = os.ReadFile(sslCertPath())
	}
	if fileExists(metaPath()) {
		oldMeta, _ = os.ReadFile(metaPath())
	}
	restore := func() {
		if oldKey == nil {
			_ = os.Remove(sslKeyPath())
		} else {
			_ = atomicWrite(sslKeyPath(), oldKey, 0o600)
		}
		if oldCert == nil {
			_ = os.Remove(sslCertPath())
		} else {
			_ = atomicWrite(sslCertPath(), oldCert, 0o644)
		}
		if oldMeta == nil {
			_ = os.Remove(metaPath())
		} else {
			_ = atomicWrite(metaPath(), oldMeta, 0o644)
		}
	}

	if err := atomicWrite(sslKeyPath(), keyPEM, 0o600); err != nil {
		restore()
		return nil, err
	}
	if err := atomicWrite(sslCertPath(), certPEM, 0o644); err != nil {
		restore()
		return nil, err
	}
	keyRaw, err := os.ReadFile(sslKeyPath())
	if err == nil {
		certRaw, err2 := os.ReadFile(sslCertPath())
		if err2 != nil {
			err = err2
		} else if _, _, err3 := validatePair(keyRaw, certRaw); err3 != nil {
			err = err3
		}
	}
	if err != nil {
		restore()
		return nil, err
	}
	writeMeta(mode)
	if oldKey != nil {
		_ = atomicWrite(previousKeyPath(), oldKey, 0o600)
	}
	if oldCert != nil {
		_ = atomicWrite(previousCertPath(), oldCert, 0o644)
	}
	_, parsed, err := validatePair(keyPEM, certPEM)
	return parsed, err
}

// --- certificate parsing + validation ---

func parseCertificatePEM(raw []byte) (*x509.Certificate, error) {
	for {
		block, rest := pem.Decode(raw)
		if block == nil {
			return nil, errors.New("the certificate file is not a valid PEM certificate.")
		}
		if block.Type == "CERTIFICATE" {
			return x509.ParseCertificate(block.Bytes)
		}
		raw = rest
	}
}

func parsePrivateKeyPEM(raw []byte) (any, error) {
	block, _ := pem.Decode(raw)
	if block == nil {
		return nil, errors.New("the key file is not a valid PEM private key.")
	}
	if strings.Contains(block.Type, "ENCRYPTED") || strings.Contains(block.Headers["Proc-Type"], "ENCRYPTED") {
		return nil, errEncryptedKey{}
	}
	if key, err := x509.ParsePKCS8PrivateKey(block.Bytes); err == nil {
		return key, nil
	}
	if key, err := x509.ParsePKCS1PrivateKey(block.Bytes); err == nil {
		return key, nil
	}
	if key, err := x509.ParseECPrivateKey(block.Bytes); err == nil {
		return key, nil
	}
	return nil, errors.New("the key file is not a valid PEM private key.")
}

type errEncryptedKey struct{}

func (errEncryptedKey) Error() string {
	return "The private key is encrypted. Remove the passphrase and upload an unencrypted PEM key."
}

// validatePair is _validate_pair: key/cert match, size caps and validity window.
func validatePair(keyBytes, certBytes []byte) (any, *x509.Certificate, error) {
	if len(keyBytes) == 0 || len(certBytes) == 0 {
		return nil, nil, errors.New("Both the private key and the certificate are required.")
	}
	if len(keyBytes) > maxTLSFileSize || len(certBytes) > maxTLSFileSize {
		return nil, nil, errors.New("Each file must be smaller than 1 MB.")
	}
	key, err := parsePrivateKeyPEM(keyBytes)
	if err != nil {
		if _, ok := err.(errEncryptedKey); ok {
			return nil, nil, err
		}
		return nil, nil, errors.New("The key file is not a valid PEM private key.")
	}
	cert, err := parseCertificatePEM(certBytes)
	if err != nil {
		return nil, nil, errors.New("The certificate file is not a valid PEM certificate.")
	}
	keyPublic, err := publicKeyDER(key)
	if err != nil {
		return nil, nil, errors.New("The key file is not a valid PEM private key.")
	}
	certPublic, err := x509.MarshalPKIXPublicKey(cert.PublicKey)
	if err != nil || string(keyPublic) != string(certPublic) {
		return nil, nil, errors.New(
			"The private key does not match the certificate. Upload the key that belongs to this certificate.")
	}
	now := time.Now()
	if cert.NotBefore.After(now.Add(5 * time.Minute)) {
		return nil, nil, fmt.Errorf("The certificate is not valid yet (starts %s). Check the server clock.",
			isoFormat(cert.NotBefore))
	}
	if !cert.NotAfter.After(now) {
		return nil, nil, fmt.Errorf("The certificate expired on %s. Upload a renewed certificate.",
			cert.NotAfter.UTC().Format("2006-01-02"))
	}
	return key, cert, nil
}

func publicKeyDER(key any) ([]byte, error) {
	// crypto.PublicKey is a defined type (not an alias for any), so the
	// `interface{ Public() any }` assertion never matches: switch on concrete
	// key types instead.
	switch k := key.(type) {
	case *rsa.PrivateKey:
		return x509.MarshalPKIXPublicKey(&k.PublicKey)
	case *ecdsa.PrivateKey:
		return x509.MarshalPKIXPublicKey(&k.PublicKey)
	case ed25519.PrivateKey:
		return x509.MarshalPKIXPublicKey(k.Public())
	}
	return nil, errors.New("unsupported private key type")
}

// isoFormat matches datetime.isoformat() (+00:00, trailing zeros
// trimmed, whole seconds without a fraction).
func isoFormat(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05.999999-07:00")
}

// --- upload / generate / renew / rollback ---

// renewRequest is POST /tls/renew's body.
type renewRequest struct {
	Domain *string `json:"domain"`
	Email  *string `json:"email"`
	UseIP  bool    `json:"use_ip"`
}
