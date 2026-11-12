// Certificate lifecycle helpers: validate a pair, activate it atomically, and
// retain the previous pair for a rollback. The panel reads the pair at startup
// and reloads it on renewal.
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
	"strings"
	"sync"
	"time"
)

// maxTLSFileSize bounds an uploaded/generated pair.
const maxTLSFileSize = 1024 * 1024

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

// certWriteMu serializes pair activations.
var certWriteMu sync.Mutex

// atomicWrite writes data beside its target then replaces it atomically. Only
// paths this module owns (the declared pair, or bookkeeping in DATA_DIR/tls)
// are allowed, checked on the resolved path so a symlink cannot redirect it.
func atomicWrite(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
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
		_ = tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}

func writeMeta(mode string) {
	meta, err := json.MarshalIndent(map[string]any{
		"mode":       mode,
		"updated_at": time.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00"),
	}, "", "  ")
	if err != nil {
		return
	}
	// Best-effort: a metadata failure must not fail an issuance.
	_ = atomicWrite(metaPath(), append(meta, '\n'), 0o644)
}

// writeManagedFiles validates and transactionally activates a certificate
// pair, restoring the previous one if any write fails. Returns the parsed cert.
func writeManagedFiles(keyPEM, certPEM []byte, mode string) (*x509.Certificate, error) {
	if _, cert, err := validatePair(keyPEM, certPEM); err != nil {
		return nil, err
	} else if cert == nil {
		return nil, errors.New("the certificate file is not a valid PEM certificate")
	}
	certWriteMu.Lock()
	defer certWriteMu.Unlock()
	if err := os.MkdirAll(tlsDir(), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
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
			return nil, errors.New("the certificate file is not a valid PEM certificate")
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
		return nil, errors.New("the key file is not a valid PEM private key")
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
	return nil, errors.New("the key file is not a valid PEM private key")
}

type errEncryptedKey struct{}

func (errEncryptedKey) Error() string {
	return "the private key is encrypted; remove the passphrase and use an unencrypted PEM key"
}

// validatePair checks that the key matches the certificate, the files are
// within the size cap, and the certificate is currently valid.
func validatePair(keyBytes, certBytes []byte) (any, *x509.Certificate, error) {
	if len(keyBytes) == 0 || len(certBytes) == 0 {
		return nil, nil, errors.New("both the private key and the certificate are required")
	}
	if len(keyBytes) > maxTLSFileSize || len(certBytes) > maxTLSFileSize {
		return nil, nil, errors.New("each file must be smaller than 1 MB")
	}
	key, err := parsePrivateKeyPEM(keyBytes)
	if err != nil {
		if _, ok := err.(errEncryptedKey); ok {
			return nil, nil, err
		}
		return nil, nil, errors.New("the key file is not a valid PEM private key")
	}
	cert, err := parseCertificatePEM(certBytes)
	if err != nil {
		return nil, nil, errors.New("the certificate file is not a valid PEM certificate")
	}
	keyPublic, err := publicKeyDER(key)
	if err != nil {
		return nil, nil, errors.New("the key file is not a valid PEM private key")
	}
	certPublic, err := x509.MarshalPKIXPublicKey(cert.PublicKey)
	if err != nil || string(keyPublic) != string(certPublic) {
		return nil, nil, errors.New("the private key does not match the certificate")
	}
	now := time.Now()
	if cert.NotBefore.After(now.Add(5 * time.Minute)) {
		return nil, nil, fmt.Errorf("the certificate is not valid yet (starts %s); check the server clock",
			isoFormat(cert.NotBefore))
	}
	if !cert.NotAfter.After(now) {
		return nil, nil, fmt.Errorf("the certificate expired on %s", cert.NotAfter.UTC().Format("2006-01-02"))
	}
	return key, cert, nil
}

func publicKeyDER(key any) ([]byte, error) {
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

func isoFormat(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05.999999-07:00")
}
