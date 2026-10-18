package panel

import (
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
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// Panel-side TLS certificate management (backend/routers/tls.py).
const (
	maxTLSFileSize     = 1024 * 1024
	acmeIssueTimeout   = 180 * time.Second
	acmeInstallTimeout = 60 * time.Second
	restartHint        = "Restart the panel to use the new certificate: " +
		"'systemctl restart ovmanager' on a native install, or 'docker restart ovmanager' for Docker."
)

// certMethods is CERT_METHODS.
var certMethods = []string{"selfsigned", "letsencrypt", "none"}

func isCertMethod(v string) bool {
	for _, m := range certMethods {
		if v == m {
			return true
		}
	}
	return false
}

// tlsEnvKeys maps an API field to (DB column, .env key).
var tlsEnvKeys = []struct {
	name, column, envKey string
}{
	{"cert_file", "ssl_cert_file", "SSL_CERTFILE"},
	{"key_file", "ssl_key_file", "SSL_KEYFILE"},
	{"acme_domain", "acme_domain", "ACME_DOMAIN"},
	{"acme_email", "acme_email", "ACME_EMAIL"},
	{"cert_method", "cert_method", "CERT_METHOD"},
}

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

// atomicWrite writes data beside its target then replaces it atomically. Only
// paths this module owns (the declared pair, or bookkeeping in DATA_DIR/tls)
// are allowed, checked on the resolved path so a symlink cannot redirect it.
func (h *Handler) atomicWrite(path string, data []byte, mode os.FileMode) error {
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

func (h *Handler) writeMeta(mode string) {
	meta, err := json.MarshalIndent(map[string]any{
		"mode":       mode,
		"updated_at": time.Now().UTC().Format("2006-01-02T15:04:05.999999-07:00"),
	}, "", "  ")
	if err != nil {
		return
	}
	// Best-effort: a metadata failure must not fail the install.
	_ = h.atomicWrite(metaPath(), append(meta, '\n'), 0o644)
}

// writeManagedFiles validates and transactionally activates a certificate pair,
// restoring the previous one if any write fails. Returns the parsed cert.
func (h *Handler) writeManagedFiles(keyPEM, certPEM []byte, mode string) (*x509.Certificate, error) {
	if _, cert, err := validatePair(keyPEM, certPEM); err != nil {
		return nil, err
	} else if cert == nil {
		return nil, errors.New("the certificate file is not a valid PEM certificate.")
	}
	h.certMu.Lock()
	defer h.certMu.Unlock()
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
			_ = h.atomicWrite(sslKeyPath(), oldKey, 0o600)
		}
		if oldCert == nil {
			_ = os.Remove(sslCertPath())
		} else {
			_ = h.atomicWrite(sslCertPath(), oldCert, 0o644)
		}
		if oldMeta == nil {
			_ = os.Remove(metaPath())
		} else {
			_ = h.atomicWrite(metaPath(), oldMeta, 0o644)
		}
	}

	if err := h.atomicWrite(sslKeyPath(), keyPEM, 0o600); err != nil {
		restore()
		return nil, err
	}
	if err := h.atomicWrite(sslCertPath(), certPEM, 0o644); err != nil {
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
	h.writeMeta(mode)
	if oldKey != nil {
		_ = h.atomicWrite(previousKeyPath(), oldKey, 0o600)
	}
	if oldCert != nil {
		_ = h.atomicWrite(previousCertPath(), oldCert, 0o644)
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

func (h *Handler) certPaths() (keyPath, certPath string) { return sslKeyPath(), sslCertPath() }

// --- status ---

// statusPayload is _status_payload.
func statusPayload(mode string, source any, certPath any, cert *x509.Certificate) map[string]any {
	out := map[string]any{
		"mode": mode, "source": source, "cert_path": certPath,
		"expires_days": nil, "expires_at": nil, "valid_from": nil, "subject": nil,
		"names": []string{}, "fingerprint_sha256": nil, "issued_by": nil,
		"restart_required": false, "previous_available": false,
	}
	if cert != nil {
		out["expires_days"] = daysUntil(cert)
		out["expires_at"] = isoFormat(cert.NotAfter)
		out["valid_from"] = isoFormat(cert.NotBefore)
		out["subject"] = cert.Subject.String()
		out["issued_by"] = classifyIssuer(cert)
		out["fingerprint_sha256"] = fingerprintSHA256(cert)
		out["names"] = certNames(cert)
	}
	if path, ok := certPath.(string); ok && path != "" {
		out["restart_required"] = restartRequired(path)
	}
	out["previous_available"] = fileExists(previousKeyPath()) && fileExists(previousCertPath())
	return out
}

// certNames is the SAN list, falling back to the legacy CN.
func certNames(cert *x509.Certificate) []string {
	names := []string{}
	if len(cert.DNSNames) > 0 || len(cert.IPAddresses) > 0 || len(cert.EmailAddresses) > 0 {
		names = append(names, cert.DNSNames...)
		for _, ip := range cert.IPAddresses {
			names = append(names, ip.String())
		}
		return names
	}
	if cert.Subject.CommonName != "" {
		names = append(names, cert.Subject.CommonName)
	}
	return names
}

// procStart is _process_start_time's fallback.
var procStart = time.Now()

// restartRequired is true when the active certificate was written after this
// process started.
func restartRequired(certPath string) bool {
	info, err := os.Stat(certPath)
	if err != nil {
		return false
	}
	start := procStart
	if procInfo, err := os.Stat("/proc/self"); err == nil {
		start = procInfo.ModTime()
	}
	return info.ModTime().After(start)
}

func (h *Handler) tlsStatus(w http.ResponseWriter, r *http.Request) {
	managedCert, managedKey := sslCertPath(), sslKeyPath()
	if fileExists(managedCert) || fileExists(managedKey) {
		if !fileExists(managedCert) || !fileExists(managedKey) {
			var path any
			if fileExists(managedCert) {
				path = managedCert
			}
			envelope(w, true, "The declared TLS files are incomplete (key and certificate are both required).",
				statusPayload("misconfigured", "declared", path, nil))
			return
		}
		cert, err := loadCertificate(managedCert)
		if err != nil {
			envelope(w, true, "The declared certificate could not be read.",
				statusPayload("misconfigured", "declared", managedCert, nil))
			return
		}
		envelope(w, true, "TLS is declared in .env.",
			statusPayload("managed", "declared", managedCert, cert))
		return
	}

	certFile := strings.TrimSpace(envOrFile("SSL_CERTFILE"))
	keyFile := strings.TrimSpace(envOrFile("SSL_KEYFILE"))
	switch {
	case certFile == "" && keyFile == "":
		envelope(w, true, "TLS is disabled, so the panel is served over plain HTTP.",
			statusPayload("disabled", nil, nil, nil))
	case certFile == "" || keyFile == "":
		var path any
		if certFile != "" {
			path = certFile
		}
		envelope(w, true, "TLS is only half configured (SSL_CERTFILE and SSL_KEYFILE must be set together).",
			statusPayload("misconfigured", "environment", path, nil))
	case !fileExists(certFile) || !fileExists(keyFile):
		envelope(w, true, "A configured TLS file is missing on disk.",
			statusPayload("misconfigured", "environment", certFile, nil))
	default:
		cert, err := loadCertificate(certFile)
		if err != nil {
			envelope(w, true, "The configured TLS certificate could not be read.",
				statusPayload("misconfigured", "environment", certFile, nil))
			return
		}
		envelope(w, true, "TLS uses certificate files configured through the environment.",
			statusPayload("files", "environment", certFile, cert))
	}
}

// --- settings ---

func (h *Handler) tlsGetSettings(w http.ResponseWriter, r *http.Request) {
	s := h.settings()
	envValues := envFileValues()
	fields := map[string]any{}
	for _, meta := range tlsEnvKeys {
		dbValue := s.nullStr(meta.column)
		var envValue any
		overridden := false
		if v := envValues[meta.envKey]; v != "" {
			envValue = v
			overridden = true
		}
		effective := dbValue
		if overridden {
			effective = envValue
		}
		var source any
		switch {
		case overridden:
			source = "env"
		case dbValue != nil:
			source = "db"
		}
		fields[meta.name] = map[string]any{
			"db": dbValue, "env": envValue, "effective": effective,
			"overridden": overridden, "source": source,
		}
	}
	envelope(w, true, "", map[string]any{
		"fields":           fields,
		"methods":          certMethods,
		"restart_required": restartRequired(sslCertPath()),
	})
}

type tlsSettingsUpdate struct {
	CertFile   *string `json:"cert_file"`
	KeyFile    *string `json:"key_file"`
	ACMEDomain *string `json:"acme_domain"`
	ACMEEmail  *string `json:"acme_email"`
	CertMethod *string `json:"cert_method"`
}

func (h *Handler) tlsPutSettings(w http.ResponseWriter, r *http.Request) {
	var payload tlsSettingsUpdate
	if !decodeBody(w, r, &payload) {
		return
	}
	if payload.CertMethod != nil && !isCertMethod(*payload.CertMethod) {
		envelope(w, false, "Unknown certificate method: "+*payload.CertMethod, nil)
		return
	}
	if payload.ACMEDomain != nil && *payload.ACMEDomain != "" && !validateDomain(*payload.ACMEDomain) {
		envelope(w, false, "That ACME domain is not valid.", nil)
		return
	}
	if payload.ACMEEmail != nil && *payload.ACMEEmail != "" && !validateEmail(*payload.ACMEEmail) {
		envelope(w, false, "That ACME email is not valid.", nil)
		return
	}

	updates := map[string]any{}
	addPath := func(name, column string, value *string) bool {
		if value == nil {
			return true
		}
		if *value == "" {
			updates[column] = nil
			return true
		}
		for _, part := range strings.Split(filepath.ToSlash(*value), "/") {
			if part == ".." {
				envelope(w, false, "The "+strings.ReplaceAll(name, "_", " ")+" must not contain '..'.", nil)
				return false
			}
		}
		abs, err := filepath.Abs(*value)
		if err != nil {
			abs = filepath.Clean(*value)
		}
		updates[column] = abs
		return true
	}
	if !addPath("cert_file", "ssl_cert_file", payload.CertFile) {
		return
	}
	if !addPath("key_file", "ssl_key_file", payload.KeyFile) {
		return
	}
	if payload.ACMEDomain != nil {
		updates["acme_domain"] = nullIfBlank(*payload.ACMEDomain)
	}
	if payload.ACMEEmail != nil {
		updates["acme_email"] = nullIfBlank(*payload.ACMEEmail)
	}
	if payload.CertMethod != nil {
		updates["cert_method"] = nullIfBlank(*payload.CertMethod)
	}
	if err := setColumns(h.Svc.DB, updates); err != nil {
		envelope(w, false, "TLS settings could not be saved", nil)
		return
	}
	envelope(w, true, "TLS settings saved. "+restartHint, map[string]any{"restart_required": true})
}

func nullIfBlank(v string) any {
	if strings.TrimSpace(v) == "" {
		return nil
	}
	return v
}

// --- upload / generate / renew / rollback ---

func (h *Handler) tlsUpload(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(maxTLSFileSize); err != nil {
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
	parsed, err := h.writeManagedFiles(keyBytes, certBytes, "custom")
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
	if _, err := h.writeManagedFiles(keyPEM, certPEM, "self-signed"); err != nil {
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

type renewRequest struct {
	Domain *string `json:"domain"`
	Email  *string `json:"email"`
	UseIP  bool    `json:"use_ip"`
}

func acmeShPath() string {
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(".acme.sh", "acme.sh")
	}
	return filepath.Join(home, ".acme.sh", "acme.sh")
}

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
		buf := make([]byte, 4)
		_, _ = cryptoRead(buf)
		email = fmt.Sprintf("acme-%x@example.com", buf)
	}

	acme := acmeShPath()
	if !fileExists(acme) {
		envelope(w, false,
			"acme.sh is not installed on this host, so the panel cannot request a Let's Encrypt certificate. "+
				"Install it on the server (curl https://get.acme.sh | sh) and retry — or upload a certificate "+
				"issued elsewhere.",
			map[string]any{"restart_required": false})
		return
	}

	if err := os.MkdirAll(tlsDir(), 0o755); err != nil {
		envelope(w, false, "Could not run acme.sh: "+err.Error(), map[string]any{"restart_required": false})
		return
	}
	issueArgs := []string{"--issue", "-d", domain, "--standalone", "--accountemail", email}
	if useIP {
		issueArgs = append(issueArgs, "--certificate-profile", "shortlived", "--days", "6")
	}
	issueOut, issueCode, issueErr := runACMEErr(acme, issueArgs, acmeIssueTimeout)
	if issueErr != nil {
		if errors.Is(issueErr, errACMETimeout) {
			envelope(w, false,
				"acme.sh timed out while issuing the certificate. Check the server's network and port 80, then retry.",
				map[string]any{"restart_required": false})
			return
		}
		envelope(w, false, "Could not run acme.sh: "+issueErr.Error(), map[string]any{"restart_required": false})
		return
	}
	if issueCode != 0 && issueCode != 2 {
		reason := lastOutputLine(issueOut, issueCode)
		envelope(w, false, fmt.Sprintf("Let's Encrypt certificate issuance failed: %s. Check that the domain points at this "+
			"server and that port 80 is reachable from the internet.", reason),
			map[string]any{"restart_required": false})
		return
	}

	staging, err := os.MkdirTemp(tlsDir(), ".acme-candidate-")
	if err != nil {
		envelope(w, false, "Could not stage the issued certificate: "+err.Error(), map[string]any{"restart_required": false})
		return
	}
	defer os.RemoveAll(staging)
	stagedKey := filepath.Join(staging, "privkey.pem")
	stagedCert := filepath.Join(staging, "fullchain.pem")
	installOut, installCode, installErr := runACMEErr(acme,
		[]string{"--install-cert", "-d", domain, "--key-file", stagedKey, "--fullchain-file", stagedCert},
		acmeInstallTimeout)
	if installErr != nil {
		if errors.Is(installErr, errACMETimeout) {
			envelope(w, false, "acme.sh timed out while installing the certificate. Retry, or upload the certificate manually.",
				map[string]any{"restart_required": false})
			return
		}
		envelope(w, false, "Could not run acme.sh: "+installErr.Error(), map[string]any{"restart_required": false})
		return
	}
	if installCode != 0 {
		reason := lastOutputLine(installOut, installCode)
		envelope(w, false, "acme.sh issued the certificate but could not install it: "+reason+".",
			map[string]any{"restart_required": false})
		return
	}

	keyPEM, err := os.ReadFile(stagedKey)
	if err != nil {
		envelope(w, false, "The issued certificate could not be activated; the previous certificate is still active: "+err.Error(),
			map[string]any{"restart_required": false, "rolled_back": true})
		return
	}
	certPEM, err := os.ReadFile(stagedCert)
	if err != nil {
		envelope(w, false, "The issued certificate could not be activated; the previous certificate is still active: "+err.Error(),
			map[string]any{"restart_required": false, "rolled_back": true})
		return
	}
	_, candidate, err := validatePair(keyPEM, certPEM)
	if err == nil && !certMatchesName(candidate, domain) {
		err = fmt.Errorf("issued certificate does not cover %s", domain)
	}
	var parsed *x509.Certificate
	if err == nil {
		parsed, err = h.writeManagedFiles(keyPEM, certPEM, "lets-encrypt")
	}
	if err != nil {
		envelope(w, false, "The issued certificate could not be activated; the previous certificate is still active: "+err.Error(),
			map[string]any{"restart_required": false, "rolled_back": true})
		return
	}
	envelope(w, true, fmt.Sprintf("Let's Encrypt certificate for %s installed. %s", domain, restartHint),
		map[string]any{
			"restart_required": true, "cert_path": sslCertPath(), "key_path": sslKeyPath(),
			"domain": domain, "expires_days": daysUntil(parsed),
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

var errACMETimeout = errors.New("acme.sh timed out")

// runACMEErr runs acme.sh; a deadline maps to errACMETimeout, a missing binary
// to the exec error.
func runACMEErr(acme string, args []string, timeout time.Duration) (string, int, error) {
	cmd := exec.Command(acme, args...)
	var out strings.Builder
	cmd.Stdout = &out
	cmd.Stderr = &out
	done := make(chan error, 1)
	if err := cmd.Start(); err != nil {
		return "", -1, err
	}
	go func() { done <- cmd.Wait() }()
	select {
	case <-done:
		return out.String(), cmd.ProcessState.ExitCode(), nil
	case <-time.After(timeout):
		_ = cmd.Process.Kill()
		<-done
		return out.String(), -1, errACMETimeout
	}
}

func lastOutputLine(output string, code int) string {
	text := strings.TrimSpace(output)
	if text == "" {
		return fmt.Sprintf("acme.sh exited with code %d", code)
	}
	lines := strings.Split(text, "\n")
	line := strings.TrimSpace(lines[len(lines)-1])
	if len(line) > 200 {
		line = line[:200]
	}
	return line
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
	parsed, err := h.writeManagedFiles(keyPEM, certPEM, "rollback")
	if err != nil {
		envelope(w, false, "Could not restore the previous certificate: "+err.Error(), nil)
		return
	}
	envelope(w, true, "Previous certificate restored. "+restartHint, map[string]any{
		"restart_required": true, "rolled_back": true, "expires_days": daysUntil(parsed),
	})
}

// --- prefix detection (for a fresh self-signed identity) ---

func (h *Handler) configuredIdentity(s settings) string {
	if envDomain := strings.TrimSpace(envFileValues()["ACME_DOMAIN"]); envDomain != "" {
		return envDomain
	}
	if domain := strings.TrimSpace(s.strOr("acme_domain")); domain != "" {
		return domain
	}
	return storedPublicIP()
}

func (h *Handler) primaryIdentity() string {
	if v := h.configuredIdentity(h.settings()); v != "" {
		return v
	}
	if v := installerPublicIP(); v != "" {
		return v
	}
	return detectPrimaryIP()
}

func primaryIP() string {
	if v := storedPublicIP(); v != "" {
		return v
	}
	if v := installerPublicIP(); v != "" {
		return v
	}
	return detectPrimaryIP()
}

// storedPublicIP is the literal address in PUBLIC_URL, when there is one.
func storedPublicIP() string {
	raw := strings.TrimSpace(envOrFile("PUBLIC_URL"))
	if raw == "" {
		return ""
	}
	if !strings.Contains(raw, "://") {
		raw = "//" + raw
	}
	host := raw
	if i := strings.Index(host, "://"); i >= 0 {
		host = host[i+3:]
	}
	if i := strings.IndexAny(host, "/?#"); i >= 0 {
		host = host[:i]
	}
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	if ip := net.ParseIP(host); ip != nil {
		return ip.String()
	}
	return ""
}

// detectPrimaryIP is _detect_primary_ip: routable IPv4 first, then hostname.
func detectPrimaryIP() string {
	routable := ""
	if out, err := exec.Command("hostname", "-I").Output(); err == nil {
		for _, token := range strings.Fields(string(out)) {
			addr := net.ParseIP(token)
			if addr == nil || addr.To4() == nil {
				continue
			}
			if !addr.IsPrivate() && !addr.IsLoopback() && !addr.IsLinkLocalUnicast() {
				return addr.String()
			}
			if routable == "" && !addr.IsLoopback() && !addr.IsLinkLocalUnicast() {
				routable = addr.String()
			}
		}
	}
	if routable != "" {
		return routable
	}
	if addrs, err := net.LookupHost(hostnameOrEmpty()); err == nil && len(addrs) > 0 {
		return addrs[0]
	}
	return "127.0.0.1"
}

func hostnameOrEmpty() string {
	name, err := os.Hostname()
	if err != nil {
		return "localhost"
	}
	return name
}

// installerPublicIP asks the same two services install.sh's public_ip() asks.
func installerPublicIP() string {
	client := &http.Client{Timeout: 3 * time.Second}
	for _, url := range []string{"https://api.ipify.org", "https://ifconfig.me/ip"} {
		resp, err := client.Get(url)
		if err != nil {
			continue
		}
		raw, err := readAtMost(resp.Body, 64)
		resp.Body.Close()
		if err != nil {
			continue
		}
		text := strings.TrimSpace(string(raw))
		if text != "" && strings.Trim(text, "0123456789abcdefABCDEF.:") == "" {
			return text
		}
	}
	// No egress: fall back to detection rather than sending a bad name to LE.
	return ""
}

// --- restart targets ---

func systemdUnitExists(unit string) bool {
	systemctl, err := exec.LookPath("systemctl")
	if err != nil {
		return false
	}
	return exec.Command(systemctl, "cat", unit).Run() == nil
}

func dockerContainerRunning(name string) bool {
	docker, err := exec.LookPath("docker")
	if err != nil {
		return false
	}
	out, err := exec.Command(docker, "inspect", "--format", "{{.State.Running}}", name).Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == "true"
}

// spawnDetached runs a fixed restart command after a short delay, detached.
func spawnDetached(argv []string) {
	args := append([]string{"-c", `sleep 1; exec "$@"`, "ovmanager-restart"}, argv...)
	cmd := exec.Command("sh", args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	cmd.SysProcAttr = detachSysProcAttr()
	_ = cmd.Start()
}

func (h *Handler) tlsRestart(w http.ResponseWriter, r *http.Request) {
	var command []string
	switch {
	case systemdUnitExists("ovmanager"):
		command = []string{"systemctl", "restart", "ovmanager"}
	case dockerContainerRunning("ovmanager"):
		command = []string{"docker", "restart", "ovmanager"}
	}
	if command == nil {
		envelope(w, false,
			"Could not restart the panel automatically. Run 'systemctl restart ovmanager' on a native "+
				"install, or 'docker restart ovmanager' for Docker.",
			map[string]any{"restart_required": true, "restarted": false, "command": "systemctl restart ovmanager"})
		return
	}
	spawnDetached(command)
	envelope(w, true, "Restarting the panel now. This page will disconnect and come back in a few seconds.",
		map[string]any{"restart_required": true, "restarted": true, "command": command})
}
