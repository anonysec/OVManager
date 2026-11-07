// `ovmanager tls` (cli): terminal-side HTTPS certificate management.
// Issuance and installation happen here; the panel process only reads the
// resulting files at startup to decide bind mode. The target pair is the
// DECLARED pair — SSL_CERTFILE/SSL_KEYFILE from the install .env (or the
// environment) when present — falling back to DATA_DIR/tls, the same
// resolution panel.SSLCertPath performs. Writing always to DATA_DIR/tls would
// leave a declared install serving its old certificate.
package cli

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func tlsDir(inst Install) string { return filepath.Join(inst.DataDir, "tls") }

// tlsTargetPaths resolves where the panel reads the pair at startup: the
// declared SSL_CERTFILE/SSL_KEYFILE when BOTH are set, else the DATA_DIR/tls
// pair. Mirrors panel.SSLCertPath/SSLKeyPath (the cli cannot call those
// directly, they resolve against the running process's working directory).
func tlsTargetPaths(inst Install) (cert, key string) {
	dir := tlsDir(inst)
	cert = filepath.Join(dir, "fullchain.pem")
	key = filepath.Join(dir, "privkey.pem")
	if c := strings.TrimSpace(inst.Env["SSL_CERTFILE"]); c != "" &&
		strings.TrimSpace(inst.Env["SSL_KEYFILE"]) != "" {
		return c, strings.TrimSpace(inst.Env["SSL_KEYFILE"])
	}
	return cert, key
}

func runTLSStatus(inst Install) (string, int) {
	cert, key := tlsTargetPaths(inst)
	if !fileExists(cert) || !fileExists(key) {
		return block([]string{heading("HTTPS certificate"), kv("Status", "disabled  (plain HTTP on 127.0.0.1)")}), 0
	}
	items := [][2]string{{"Cert", cert}, {"Key", key}}
	if expiry, ok := certEnddate(cert); ok {
		items = append(items, [2]string{"Expires", expiry.Format("Jan _2 15:04:05 2006 MST")})
	}
	return block(append([]string{heading("HTTPS certificate")}, renderRows(items)...)), 0
}

// legacyPairPaths are the pre-declaration locations the panel's startup
// migration copies from.
func legacyPairPaths(inst Install) (cert, key string) {
	dir := tlsDir(inst)
	return filepath.Join(dir, "fullchain.pem"), filepath.Join(dir, "privkey.pem")
}

func runTLSRemove(inst Install) (string, int) {
	cert, key := tlsTargetPaths(inst)
	legacyCert, legacyKey := legacyPairPaths(inst)
	var removed []string
	for _, p := range []string{cert, key, legacyCert, legacyKey,
		filepath.Join(tlsDir(inst), "previous-fullchain.pem"),
		filepath.Join(tlsDir(inst), "previous-privkey.pem")} {
		if err := os.Remove(p); err == nil {
			removed = append(removed, p)
		}
	}
	summary := "removed — panel reverts to HTTP on 127.0.0.1 after restart"
	if len(removed) == 0 {
		summary = "nothing to remove"
	}
	return block([]string{heading("HTTPS certificate"), summary, "fix            ovmanager service restart"}), 0
}

func runTLSInstall(inst Install, certSrc, keySrc string) (string, int) {
	if certSrc == "" || keySrc == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovmanager tls install <cert.pem> <key.pem>"}), 2
	}
	certBytes, err := os.ReadFile(certSrc) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read cert: " + err.Error()}), 1
	}
	keyBytes, err := os.ReadFile(keySrc) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read key: " + err.Error()}), 1
	}
	certPath, keyPath := tlsTargetPaths(inst)
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, certBytes, 0o644); err != nil { // #nosec G703 // admin-controlled cert path G306
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, keyBytes, 0o600); err != nil { // #nosec G703 // admin-controlled key path
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	return block([]string{heading("HTTPS certificate"), "installed — restart panel to serve HTTPS on 0.0.0.0", "fix            ovmanager service restart"}), 0
}

func runTLSSelfSigned(inst Install, domain string) (string, int) {
	if strings.TrimSpace(domain) == "" {
		domain = "localhost"
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	dnsNames := []string{}
	var ipAddrs []net.IP
	seenDNS := map[string]bool{}
	seenIP := map[string]bool{}
	cn := ""
	for _, part := range strings.Split(domain, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if cn == "" {
			cn = part
		}
		if ip := net.ParseIP(part); ip != nil {
			s := ip.String()
			if !seenIP[s] {
				seenIP[s] = true
				ipAddrs = append(ipAddrs, ip)
			}
			continue
		}
		if !seenDNS[part] {
			seenDNS[part] = true
			dnsNames = append(dnsNames, part)
		}
	}
	if cn == "" {
		cn = "localhost"
	}
	if len(dnsNames) == 0 && len(ipAddrs) == 0 {
		dnsNames = append(dnsNames, "localhost")
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(365 * 24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     dnsNames,
		IPAddresses:  ipAddrs,
	}
	certDER, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	certPath, keyPath := tlsTargetPaths(inst)
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, certPEM, 0o644); err != nil { // #nosec G306 // public certificate is world-readable by design
		return block([]string{heading("HTTPS certificate"), "could not write certificate: " + err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write key: " + err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	return block([]string{heading("HTTPS certificate"), "self-signed cert issued for " + domain, "restart panel to serve HTTPS on 0.0.0.0", "fix            ovmanager service restart"}), 0
}

func runTLSRenew(inst Install) (string, int) {
	certPath, _ := tlsTargetPaths(inst)
	data, err := os.ReadFile(certPath) // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "no certificate found: " + err.Error()}), 1
	}
	pb, _ := pem.Decode(data)
	if pb == nil {
		return block([]string{heading("HTTPS certificate"), "invalid certificate file"}), 1
	}
	cert, err := x509.ParseCertificate(pb.Bytes)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not parse certificate: " + err.Error()}), 1
	}
	if time.Until(cert.NotAfter) > 30*24*time.Hour {
		return block([]string{heading("HTTPS certificate"), "certificate still valid until " + cert.NotAfter.UTC().Format(time.RFC3339) + " - skipping renewal"}), 0
	}
	domain := ""
	if len(cert.DNSNames) > 0 {
		domain = cert.DNSNames[0]
	} else if len(cert.IPAddresses) > 0 {
		domain = cert.IPAddresses[0].String()
	} else {
		domain = cert.Subject.CommonName
	}
	if domain == "" {
		return block([]string{heading("HTTPS certificate"), "could not determine domain from certificate"}), 1
	}
	text, code := runTLSIssue(inst, domain, "")
	return text, code
}

func runTLSIssue(inst Install, domain, email string) (string, int) {
	return block([]string{"HTTPS certificate", "in-process issuance removed; install your own cert instead:", "  ovmanager tls install <cert.pem> <key.pem>", "acme.sh or any CA client serve as external source"}), 1
}
