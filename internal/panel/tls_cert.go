// Certificate lifecycle. The managed-pair pipeline: validate, atomic replace,
// retain the previous pair. Plus the parsing/validation helpers behind it, the
// upload endpoint, self-signed generation, the single-issuance renew endpoint
// (POST /tls/renew, POST /https/automatic) and rollback.
package panel

import (
	"context"
	"crypto/ecdsa"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"math/big"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Panel-side TLS certificate management (backend/routers/tls.py).
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

func validateEmail(value string) bool { return value != "" && emailRe.MatchString(value) }

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
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
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
	if err := os.MkdirAll(tlsDir(), 0o755); err != nil {
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

func (h *Handler) tlsUpload(w http.ResponseWriter, r *http.Request) {
	// MaxBytesReader is the actual body limit: ParseMultipartForm only caps the
	// in-memory portion and spools the rest to disk.
	// The body carries BOTH the key and the certificate, each up to
	// maxTLSFileSize, so the body cap is twice the per-file cap.
	r.Body = http.MaxBytesReader(w, r.Body, 2*maxTLSFileSize+64*1024)
	// The parser spools a file part over the in-memory limit to the system
	// temp dir; the request has to clean it up.
	defer removeMultipartTemps(r)
	if err := r.ParseMultipartForm(maxTLSFileSize); err != nil {
		var tooBig *http.MaxBytesError
		if errors.As(err, &tooBig) {
			writeValidationError(w, "too_large", "key",
				fmt.Sprintf("Each file must be smaller than %d bytes", maxTLSFileSize))
			return
		}
		writeValidationBody(w, "key", "field required")
		return
	}
	keyBytes, ok := readUpload(r, "key")
	if !ok {
		writeValidationBody(w, "key", "field required")
		return
	}
	certBytes, ok := readUpload(r, "cert")
	if !ok {
		writeValidationBody(w, "cert", "field required")
		return
	}
	if _, _, err := validatePair(keyBytes, certBytes); err != nil {
		envelope(w, false, err.Error(), nil)
		return
	}
	parsed, err := writeManagedFiles(keyBytes, certBytes, "custom")
	if err != nil {
		envelope(w, false, "Could not save the certificate files: "+err.Error(), nil)
		return
	}
	subject := ""
	if parsed != nil {
		subject = parsed.Subject.String()
	}
	_ = subject // logged by the router; the response is what the API contract pins
	envelope(w, true, "Certificate installed. "+restartHint, map[string]any{
		"restart_required": true, "cert_path": sslCertPath(), "key_path": sslKeyPath(),
	})
}

// readUpload reads one multipart file field, capped at 1MB+1 like the original
// `await file.read(MAX_TLS_FILE_SIZE + 1)`.
func readUpload(r *http.Request, field string) ([]byte, bool) {
	file, _, err := r.FormFile(field)
	if err != nil {
		return nil, false
	}
	defer file.Close()
	buf, err := readAtMost(file, maxTLSFileSize+1)
	if err != nil {
		return nil, false
	}
	return buf, true
}

func (h *Handler) tlsSelfSigned(w http.ResponseWriter, r *http.Request) {
	cn := h.primaryIdentity()
	keyPEM, certPEM, err := buildSelfSigned(cn)
	if err != nil {
		envelope(w, false, "Could not create a self-signed certificate: "+err.Error(), nil)
		return
	}
	if _, err := writeManagedFiles(keyPEM, certPEM, "self-signed"); err != nil {
		envelope(w, false, "Could not create a self-signed certificate: "+err.Error(), nil)
		return
	}
	envelope(w, true, "A new self-signed certificate for "+cn+" was created. "+restartHint, map[string]any{
		"restart_required": true, "cert_path": sslCertPath(), "key_path": sslKeyPath(), "common_name": cn,
	})
}

// buildSelfSigned is RSA 2048 / 10 years, the installer's openssl profile.
func buildSelfSigned(commonName string) ([]byte, []byte, error) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, nil, err
	}
	subject := pkix.Name{
		Country:      []string{"US"},
		Province:     []string{"Local"},
		Locality:     []string{"Local"},
		Organization: []string{"OVManager"},
		CommonName:   commonName,
	}
	now := time.Now()
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return nil, nil, err
	}
	tmpl := &x509.Certificate{
		SerialNumber:          serial,
		Subject:               subject,
		Issuer:                subject,
		NotBefore:             now.Add(-5 * time.Minute),
		NotAfter:              now.Add(3650 * 24 * time.Hour),
		BasicConstraintsValid: true,
		IsCA:                  true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
	}
	if ip := net.ParseIP(commonName); ip != nil {
		tmpl.IPAddresses = []net.IP{ip}
	} else {
		tmpl.DNSNames = []string{commonName}
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		return nil, nil, err
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, nil, err
	}
	return pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}),
		pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), nil
}

// renewRequest is POST /tls/renew's body.
type renewRequest struct {
	Domain *string `json:"domain"`
	Email  *string `json:"email"`
	UseIP  bool    `json:"use_ip"`
}

// tlsRenew is POST /tls/renew (POST /https/automatic): ONE issuance path — the
// panel's built-in ACME client through runIssuance, the same flow as
// POST /tls/acme plus the IP-address option. The old acme.sh shell path is
// retired: one implementation instead of three issuance code paths.
func (h *Handler) tlsRenew(w http.ResponseWriter, r *http.Request) {
	var payload renewRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	s := h.settings()
	method := s.strOr("cert_method")
	useIP := payload.UseIP
	domain := ""
	if useIP {
		domain = primaryIP()
	} else {
		if payload.Domain != nil {
			domain = strings.TrimSpace(*payload.Domain)
		}
		if domain == "" {
			domain = strings.TrimSpace(s.strOr("acme_domain"))
		}
	}
	if domain == "" {
		if method == "selfsigned" {
			envelope(w, false, "Not applicable: the panel is set to a self-signed certificate.", nil)
			return
		}
		envelope(w, false, "Add the domain name to request a Let's Encrypt certificate, or select the IP-address option.", nil)
		return
	}
	if useIP {
		addr := net.ParseIP(domain)
		if addr == nil {
			envelope(w, false, "Could not detect a valid server IP address.", nil)
			return
		}
		if !addr.IsGlobalUnicast() || addr.IsPrivate() {
			envelope(w, false, "Automatic IP certificates require a publicly routable server IP.", nil)
			return
		}
	} else if !validateDomain(domain) {
		envelope(w, false, "That domain name is not valid. Use letters, digits, dots and hyphens only.", nil)
		return
	}
	// Never invent a contact address: a fake one silently eats the expiry
	// notices. The request body or the saved acme_email setting must name a
	// real address before any issuance runs.
	email := ""
	if payload.Email != nil {
		email = strings.TrimSpace(*payload.Email)
	}
	if email == "" {
		email = strings.TrimSpace(s.strOr("acme_email"))
	}
	if email != "" && !validateEmail(email) {
		envelope(w, false, "That email address is not valid. Use a real address so expiry notices can reach you.", nil)
		return
	}
	if email == "" {
		envelope(w, false,
			"A contact email address is required before a Let's Encrypt certificate can be issued. "+
				"Set the ACME email in Settings and retry — renewal warnings are sent there.", nil)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), acmeHTTPIssueTimeout)
	defer cancel()
	res, err := h.runIssuance(ctx, domain)
	if err != nil {
		envelope(w, false,
			fmt.Sprintf("Let's Encrypt certificate issuance failed: %v. The previous certificate is still active.", err),
			map[string]any{"restart_required": false})
		return
	}
	// The pair is active on disk; make sure a settings row exists before
	// pointing the SSL_* columns at it (readSettings seeds the row — a fresh
	// install has none, and a 0-row UPDATE would silently pass).
	readSettings(h.Svc.DB())
	_ = setColumns(h.Svc.DB(), map[string]any{
		"ssl_cert_file": sslCertPath(), "ssl_key_file": sslKeyPath(),
	})
	envelope(w, true, fmt.Sprintf("Let's Encrypt certificate for %s installed. %s", domain, restartHint),
		map[string]any{
			"restart_required": true, "cert_path": sslCertPath(), "key_path": sslKeyPath(),
			"domain": domain, "expires_days": res.expiresDays,
		})
}

// certMatchesName is _certificate_matches_name: SAN (or CN) covers the name.
func certMatchesName(cert *x509.Certificate, expected string) bool {
	if cert == nil {
		return false
	}
	if ip := net.ParseIP(expected); ip != nil {
		for _, candidate := range cert.IPAddresses {
			if candidate.Equal(ip) {
				return true
			}
		}
		if len(cert.IPAddresses) == 0 && cert.Subject.CommonName == expected {
			return true
		}
		return false
	}
	if len(cert.DNSNames) == 0 {
		return strings.EqualFold(cert.Subject.CommonName, expected)
	}
	for _, name := range cert.DNSNames {
		if strings.EqualFold(name, expected) {
			return true
		}
	}
	return false
}

func (h *Handler) tlsRollback(w http.ResponseWriter, r *http.Request) {
	if !fileExists(previousKeyPath()) || !fileExists(previousCertPath()) {
		envelope(w, false, "No previous HTTPS certificate is available.", nil)
		return
	}
	keyPEM, err := os.ReadFile(previousKeyPath())
	if err != nil {
		envelope(w, false, "Could not restore the previous certificate: "+err.Error(), nil)
		return
	}
	certPEM, err := os.ReadFile(previousCertPath())
	if err != nil {
		envelope(w, false, "Could not restore the previous certificate: "+err.Error(), nil)
		return
	}
	parsed, err := writeManagedFiles(keyPEM, certPEM, "rollback")
	if err != nil {
		envelope(w, false, "Could not restore the previous certificate: "+err.Error(), nil)
		return
	}
	envelope(w, true, "Previous certificate restored. "+restartHint, map[string]any{
		"restart_required": true, "rolled_back": true, "expires_days": daysUntil(parsed),
	})
}
