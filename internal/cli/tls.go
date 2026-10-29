// `ovm tls` (cli): terminal-side HTTPS certificate management.
// Issuance and installation happen here; the panel process only reads the
// resulting files at startup to decide bind mode. The target pair is the
// DECLARED pair — SSL_CERTFILE/SSL_KEYFILE from the install .env (or the
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

	"github.com/anonysec/OVManager/go/internal/acme"
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
	return block([]string{heading("HTTPS certificate"), summary, "fix            ovm service restart"}), 0
}

func runTLSInstall(inst Install, certSrc, keySrc string) (string, int) {
	if certSrc == "" || keySrc == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovmanager tls install <cert.pem> <key.pem>"}), 2
	}
	certBytes, err := os.ReadFile(certSrc)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read cert: " + err.Error()}), 1
	}
	keyBytes, err := os.ReadFile(keySrc)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read key: " + err.Error()}), 1
	}
	certPath, keyPath := tlsTargetPaths(inst)
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, certBytes, 0o644); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, keyBytes, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	return block([]string{heading("HTTPS certificate"), "installed — restart panel to serve HTTPS on 0.0.0.0", "fix            ovm service restart"}), 0
}

func runTLSSelfSigned(inst Install, domain string) (string, int) {
	if domain == "" {
		domain = "localhost"
	}
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	dnsNames := []string{}
	var ipAddrs []net.IP
	if ip := net.ParseIP(domain); ip != nil {
		ipAddrs = append(ipAddrs, ip)
	} else if domain != "" {
		dnsNames = append(dnsNames, domain)
	}
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: domain},
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
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, certPEM, 0o644); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write certificate: " + err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, keyPEM, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write key: " + err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	return block([]string{heading("HTTPS certificate"), "self-signed cert issued for " + domain, "restart panel to serve HTTPS on 0.0.0.0", "fix            ovm service restart"}), 0
}

func runTLSRenew(inst Install) (string, int) {
	certPath, _ := tlsTargetPaths(inst)
	data, err := os.ReadFile(certPath)
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
	text, code := runTLSAcme(inst, domain, "")
	return text, code
}

// port80Occupant returns the process name and (best-effort) systemd unit
// holding port 80, plus whether one was found.
func port80Occupant() (proc string, unit string, found bool) {
	out, err := exec.Command("ss", "-tlnp", "sport = :80").Output()
	if err != nil {
		return "", "", false
	}
	re := regexp.MustCompile(`pid=(\d+)`)
	m := re.FindStringSubmatch(string(out))
	if m == nil {
		return "", "", false
	}
	pid := m[1]
	data, err := os.ReadFile("/proc/" + pid + "/comm")
	if err != nil {
		return "", "", false
	}
	proc = strings.TrimSpace(string(data))
	// try cgroup for the systemd unit
	cg, _ := os.ReadFile("/proc/" + pid + "/cgroup")
	for _, line := range strings.Split(string(cg), "\n") {
		if i := strings.Index(line, ".service"); i >= 0 {
			// extract the unit name
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
		// fallback mapping by process name
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

func runTLSAcme(inst Install, domain, email string) (string, int) {
	if domain == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovmanager tls acme <domain> [email]"}), 2
	}

	// If port 80 is busy, offer to free it temporarily (with confirmation).
	conn, err := net.DialTimeout("tcp", "127.0.0.1:80", 2*time.Second)
	if err == nil {
		conn.Close()
		proc, unit, found := port80Occupant()
		msg := "port 80 is in use"
		if found && proc != "" {
			msg = "port 80 is in use by " + proc
		}
		// determine TTY
		isTTY := false
		if fi, _ := os.Stdin.Stat(); fi != nil && (fi.Mode()&os.ModeCharDevice) != 0 {
			isTTY = true
		}
		if !isTTY {
			return block([]string{
				heading("HTTPS certificate"),
				msg,
				"free port 80 and retry, or run interactively to confirm auto-stop.",
			}), 1
		}
		if unit == "" {
			return block([]string{
				heading("HTTPS certificate"),
				msg,
				"could not map it to a systemd service; free port 80 manually and retry.",
			}), 1
		}
		fmt.Fprintf(os.Stderr, "%s\nStop %s temporarily to free port 80? [y/N]: ", msg, unit)
		var answer string
		fmt.Scanln(&answer)
		answer = strings.TrimSpace(strings.ToLower(answer))
		if answer != "y" && answer != "yes" {
			return block([]string{
				heading("HTTPS certificate"),
				"aborted - port 80 left untouched.",
			}), 1
		}
		// stop
		if err := exec.Command("systemctl", "stop", unit).Run(); err != nil {
			return block([]string{heading("HTTPS certificate"), "could not stop " + unit + ": " + err.Error()}), 1
		}
		// restart on exit (success or failure)
		defer func(u string) {
			_ = exec.Command("systemctl", "start", u).Run()
		}(unit)
		// wait briefly for port to be released
		for i := 0; i < 20; i++ {
			c, err := net.DialTimeout("tcp", "127.0.0.1:80", 500*time.Millisecond)
			if err != nil {
				break
			}
			c.Close()
			time.Sleep(250 * time.Millisecond)
		}
	}

	// account key
	dir := tlsDir(inst)
	if err := os.MkdirAll(dir, 0o755); err != nil {
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
		Domains:    []string{domain},
		AccountKey: key,
		HTTPPort:   80,
		Profile:    profile,
	})
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "acme failed: " + err.Error()}), 1
	}
	certPath, keyPath := tlsTargetPaths(inst)
	if err := os.MkdirAll(filepath.Dir(certPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(certPath, res.CertPEM, 0o644); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write certificate: " + err.Error()}), 1
	}
	if err := os.WriteFile(keyPath, res.KeyPEM, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), "could not write key: " + err.Error()}), 1
	}
	_ = fixTLSOwnership(certPath, 0o644)
	_ = fixTLSOwnership(keyPath, 0o600)
	// persist account key if returned
	if len(res.AccountKeyPEM) > 0 {
		if err := os.WriteFile(acctPath, res.AccountKeyPEM, 0o600); err != nil {
			return block([]string{heading("HTTPS certificate"), "could not persist the ACME account key: " + err.Error()}), 1
		}
	}
	_ = email
	return block([]string{heading("HTTPS certificate"), fmt.Sprintf("Let's Encrypt cert issued for %s", domain), "restart panel to serve HTTPS on 0.0.0.0", "fix            ovm service restart"}), 0
}

func loadOrCreateAccountKeyCLI(path string) (crypto.Signer, error) {
	if raw, err := os.ReadFile(path); err == nil {
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
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		return nil, err
	}
	return key, nil
}
