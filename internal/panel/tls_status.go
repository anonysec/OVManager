// TLS status and settings: GET/PUT /tls/settings (and the /https aliases),
// GET /tls/status, and the restartRequired probe with its process-start
// fallback.
package panel

import (
	"crypto/x509"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
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

// procStart is _process_start_time's fallback, taken at package init: on
// platforms without /proc/self it is the closest available proxy for "when
// this process started".
var procStart = time.Now()

// restartRequired is true when the active certificate was written after this
// process started.
//
// LIMITATION (Linux/Docker): the start timestamp comes from /proc/self's
// mtime, which only exists on Linux, and inside a container it reflects the
// container's start rather than a host clock. On other platforms os.Stat
// fails and the package-init procStart proxy is used instead. No behavior
// change for non-Linux hosts is possible without a cross-platform start-time
// source.
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
	if err := setColumns(h.Svc.DB(), updates); err != nil {
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
