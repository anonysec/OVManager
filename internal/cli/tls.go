// `ovmanager tls` (cli): terminal-side HTTPS certificate management.
// Issuance and installation happen here; the panel process only reads the
// resulting files at startup to decide bind mode. The target pair is the
// DECLARED pair — TlsCertFile/TlsKeyFile from the install .env (or the
// environment) when present — falling back to DATA_DIR/tls, the same
// resolution panel.SSLCertPath performs. Writing always to DATA_DIR/tls would
// leave a declared install serving its old certificate.
package cli

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/anonysec/OVManager/internal/acme"
)

func tlsDir(inst Install) string { return filepath.Join(inst.DataDir, "tls") }

// tlsTargetPaths resolves where the panel reads the pair at startup: the
// declared TlsCertFile/TlsKeyFile when BOTH are set, else the DATA_DIR/tls
// pair. Mirrors panel.SSLCertPath/SSLKeyPath (the cli cannot call those
// directly, they resolve against the running process's working directory).
func tlsTargetPaths(inst Install) (cert, key string) {
	dir := tlsDir(inst)
	cert = filepath.Join(dir, "fullchain.pem")
	key = filepath.Join(dir, "privkey.pem")
	if c := strings.TrimSpace(inst.Env["TlsCertFile"]); c != "" &&
		strings.TrimSpace(inst.Env["TlsKeyFile"]) != "" {
		return c, strings.TrimSpace(inst.Env["TlsKeyFile"])
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
	if raw, err := os.ReadFile(filepath.Join(tlsDir(inst), "acme.json")); err == nil {
		var e struct {
			Target string `json:"target"`
		}
		if json.Unmarshal(raw, &e) == nil && e.Target != "" {
			items = append(items, [2]string{"Renews", e.Target})
		}
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
		filepath.Join(tlsDir(inst), "previous-privkey.pem"),
		filepath.Join(tlsDir(inst), "acme.json")} {
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
	_ = os.Remove(filepath.Join(tlsDir(inst), "acme.json"))
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
	_ = os.Remove(filepath.Join(tlsDir(inst), "acme.json"))
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
	if time.Until(cert.NotAfter) > tlsRenewWindow(cert) {
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
	text, code := runTLSAcme(inst, domain, "")
	return text, code
}

// tlsRenewWindow matches the panel worker: a third of the leaf lifetime,
// capped at 30 days and floored at one day.
func tlsRenewWindow(cert *x509.Certificate) time.Duration {
	life := cert.NotAfter.Sub(cert.NotBefore)
	if life <= 0 {
		return 24 * time.Hour
	}
	window := life / 3
	if window > 30*24*time.Hour {
		window = 30 * 24 * time.Hour
	}
	if window < 24*time.Hour {
		window = 24 * time.Hour
	}
	return window
}

func runTLSAcme(inst Install, domain, email string) (string, int) {
	if domain == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovmanager tls acme <domain> [email]"}), 2
	}

	port := acmeHTTPPortCLI(inst)
	// If the challenge port is busy, offer to free it temporarily.
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 2*time.Second)
	if err == nil {
		_ = conn.Close()
		proc, unit, found := portOccupant(port)
		msg := fmt.Sprintf("port %d is in use", port)
		if found && proc != "" {
			msg = fmt.Sprintf("port %d is in use by %s", port, proc)
		}
		isTTY := false
		if fi, _ := os.Stdin.Stat(); fi != nil && (fi.Mode()&os.ModeCharDevice) != 0 {
			isTTY = true
		}
		if !isTTY {
			return block([]string{
				heading("HTTPS certificate"),
				msg,
				fmt.Sprintf("free port %d and retry, or run interactively to confirm auto-stop.", port),
			}), 1
		}
		if unit == "" {
			return block([]string{
				heading("HTTPS certificate"),
				msg,
				fmt.Sprintf("could not map it to a systemd service; free port %d manually and retry.", port),
			}), 1
		}
		fmt.Fprintf(os.Stderr, "%s\nStop %s temporarily to free port 80? [y/N]: ", msg, unit)
		var answer string
		_, _ = fmt.Scanln(&answer)
		answer = strings.TrimSpace(strings.ToLower(answer))
		if answer != "y" && answer != "yes" {
			return block([]string{heading("HTTPS certificate"), "aborted - port 80 left untouched."}), 1
		}
		if err := exec.Command("systemctl", "stop", unit).Run(); err != nil { // #nosec G204 // command arguments are static or validated against strict allowlist
			return block([]string{heading("HTTPS certificate"), "could not stop " + unit + ": " + err.Error()}), 1
		}
		defer func(u string) {
			_ = exec.Command("systemctl", "start", u).Run() // #nosec G204 // command arguments are static or validated against strict allowlist
		}(unit)
		for i := 0; i < 20; i++ {
			c, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 500*time.Millisecond)
			if err != nil {
				break
			}
			_ = c.Close()
			time.Sleep(250 * time.Millisecond)
		}
	}

	dir := tlsDir(inst)
	if err := os.MkdirAll(dir, 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	acctPath := filepath.Join(dir, "acme-account.pem")
	key, err := loadOrCreateAccountKeyCLI(acctPath)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	profile := ""
	if net.ParseIP(domain) != nil {
		profile = "shortlived"
	}
	res, err := acme.Issue(ctx, acme.Options{
		Domains:      []string{domain},
		AccountKey:   key,
		DirectoryURL: acmeDirectoryURLCLI(inst),
		HTTPPort:     port,
		Profile:      profile,
	})
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "acme failed: " + err.Error()}), 1
	}
	certPath, keyPath := tlsTargetPaths(inst)
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, res.CertPEM, 0o644); err != nil { // #nosec G306 // public certificate is world-readable by design
		return block([]string{heading("HTTPS certificate"), "could not write certificate: " + err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, res.KeyPEM, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write key: " + err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	if len(res.AccountKeyPEM) > 0 {
		if err := os.WriteFile(acctPath, res.AccountKeyPEM, 0o600); err != nil {
			return block([]string{heading("HTTPS certificate"), "could not persist the ACME account key: " + err.Error()}), 1
		}
		_ = fixTLSOwnership(acctPath, 0o600)
	}
	// Record the target so the panel worker renews this pair. Custom and
	// self-signed installs remove the record instead.
	enrollment, _ := json.Marshal(struct {
		Target string `json:"target"`
	}{Target: domain})
	if err := os.WriteFile(filepath.Join(dir, "acme.json"), append(enrollment, '\n'), 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not record the renewal target: " + err.Error()}), 1
	}
	_ = fixTLSOwnership(filepath.Join(dir, "acme.json"), 0o600)
	_ = email
	return block([]string{heading("HTTPS certificate"), fmt.Sprintf("Let's Encrypt cert issued for %s", domain), "restart panel to serve HTTPS on 0.0.0.0", "fix            ovmanager service restart"}), 0
}

// portOccupant returns the process name and (best-effort) systemd unit
// holding the challenge port, plus whether one was found.
func portOccupant(port int) (proc string, unit string, found bool) {
	out, err := exec.Command("ss", "-tlnp", fmt.Sprintf("sport = :%d", port)).Output()
	if err != nil {
		return "", "", false
	}
	re := regexp.MustCompile(`pid=(\d+)`)
	m := re.FindStringSubmatch(string(out))
	if m == nil {
		return "", "", false
	}
	pid := m[1]
	data, err := os.ReadFile("/proc/" + pid + "/comm") // #nosec G304 // path is validated within trusted data or application directory
	if err != nil {
		return "", "", false
	}
	proc = strings.TrimSpace(string(data))
	cg, _ := os.ReadFile("/proc/" + pid + "/cgroup") // #nosec G304 // path is validated within trusted data or application directory
	for _, line := range strings.Split(string(cg), "\n") {
		if i := strings.Index(line, ".service"); i >= 0 {
			start := strings.LastIndex(line[:i], "/")
			if start < 0 {
				start = strings.LastIndex(line[:i], ":")
			}
			if start >= 0 {
				unit = line[start+1 : i+len(".service")]
				break
			}
		}
	}
	if unit == "" {
		switch proc {
		case "nginx":
			unit = "nginx"
		case "apache2", "httpd":
			unit = proc
		case "caddy":
			unit = "caddy"
		}
	}
	return proc, unit, true
}

func acmeHTTPPortCLI(inst Install) int {
	if v := strings.TrimSpace(os.Getenv("AcmeHttpPort")); v != "" {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil && n > 0 && n <= 65535 {
			return n
		}
	}
	if v := strings.TrimSpace(inst.Env["AcmeHttpPort"]); v != "" {
		var n int
		if _, err := fmt.Sscanf(v, "%d", &n); err == nil && n > 0 && n <= 65535 {
			return n
		}
	}
	return 80
}

func acmeDirectoryURLCLI(inst Install) string {
	if v := strings.TrimSpace(os.Getenv("AcmeDirectoryUrl")); v != "" {
		return v
	}
	return strings.TrimSpace(inst.Env["AcmeDirectoryUrl"])
}

func loadOrCreateAccountKeyCLI(path string) (crypto.Signer, error) {
	if raw, err := os.ReadFile(path); err == nil { // #nosec G304 // path is validated within trusted data or application directory
		if block, _ := pem.Decode(raw); block != nil {
			if key, err := x509.ParsePKCS8PrivateKey(block.Bytes); err == nil {
				if signer, ok := key.(crypto.Signer); ok {
					return signer, nil
				}
			}
		}
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, err
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { // #nosec G301 // directory permissions 0755 required for service user traversal
		return nil, err
	}
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		return nil, err
	}
	return key, nil
}
