// `ovm tls` (cli/tls.py): terminal-side HTTPS certificate management.
// Issuance and installation happen here; the panel process only reads the
// resulting files from DATA_DIR/tls at startup to decide bind mode.
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
	"math/big"
	"os"
	"path/filepath"
	"time"

	"github.com/anonysec/OVManager/go/internal/acme"
)

func tlsDir(inst Install) string { return filepath.Join(inst.DataDir, "tls") }

func runTLSStatus(inst Install) (string, int) {
	cert := filepath.Join(tlsDir(inst), "fullchain.pem")
	key := filepath.Join(tlsDir(inst), "privkey.pem")
	if !fileExists(cert) || !fileExists(key) {
		return block([]string{heading("HTTPS certificate"), kv("Status", "disabled  (plain HTTP on 127.0.0.1)")}), 0
	}
	items := [][2]string{{"Cert", cert}, {"Key", key}}
	if expiry, ok := certEnddate(cert); ok {
		items = append(items, [2]string{"Expires", expiry.Format("Jan _2 15:04:05 2006 MST")})
	}
	return block(append([]string{heading("HTTPS certificate")}, renderRows(items)...)), 0
}

func runTLSRemove(inst Install) (string, int) {
	dir := tlsDir(inst)
	for _, name := range []string{"fullchain.pem", "privkey.pem", "previous-fullchain.pem", "previous-privkey.pem"} {
		_ = os.Remove(filepath.Join(dir, name))
	}
	return block([]string{heading("HTTPS certificate"), "removed — panel reverts to HTTP on 127.0.0.1 after restart", "fix            ovm service restart"}), 0
}

func runTLSInstall(inst Install, certSrc, keySrc string) (string, int) {
	if certSrc == "" || keySrc == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovm tls install <cert.pem> <key.pem>"}), 2
	}
	certBytes, err := os.ReadFile(certSrc)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read cert: " + err.Error()}), 1
	}
	keyBytes, err := os.ReadFile(keySrc)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "could not read key: " + err.Error()}), 1
	}
	dir := tlsDir(inst)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(filepath.Join(dir, "fullchain.pem"), certBytes, 0o644); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	if err := os.WriteFile(filepath.Join(dir, "privkey.pem"), keyBytes, 0o600); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
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
	tmpl := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: domain},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(365 * 24 * time.Hour),
		KeyUsage:      x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:   []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:      []string{domain},
	}
	certDER, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	dir := tlsDir(inst)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	// write cert
	cf, _ := os.Create(filepath.Join(dir, "fullchain.pem"))
	cf.Write(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER}))
	cf.Close()
	// write key
	kf, _ := os.Create(filepath.Join(dir, "privkey.pem"))
	keyDER, _ := x509.MarshalPKCS8PrivateKey(key)
	kf.Write(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}))
	kf.Close()
	_ = os.Chmod(filepath.Join(dir, "privkey.pem"), 0o600)
	return block([]string{heading("HTTPS certificate"), "self-signed cert issued for " + domain, "restart panel to serve HTTPS on 0.0.0.0", "fix            ovm service restart"}), 0
}

func runTLSAcme(inst Install, domain, email string) (string, int) {
	if domain == "" {
		return block([]string{heading("HTTPS certificate"), "usage: ovm tls acme <domain> [email]"}), 2
	}
	// account key
	acctPath := filepath.Join(tlsDir(inst), "acme-account.pem")
	key, err := loadOrCreateAccountKeyCLI(acctPath)
	if err != nil {
		return block([]string{heading("HTTPS certificate"), err.Error()}), 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	res, err := acme.Issue(ctx, acme.Options{
		Domains:    []string{domain},
		AccountKey: key,
		HTTPPort:   80,
	})
	if err != nil {
		return block([]string{heading("HTTPS certificate"), "acme failed: " + err.Error()}), 1
	}
	dir := tlsDir(inst)
	_ = os.MkdirAll(dir, 0o755)
	_ = os.WriteFile(filepath.Join(dir, "fullchain.pem"), res.CertPEM, 0o644)
	_ = os.WriteFile(filepath.Join(dir, "privkey.pem"), res.KeyPEM, 0o600)
	// persist account key if returned
	if len(res.AccountKeyPEM) > 0 {
		_ = os.WriteFile(acctPath, res.AccountKeyPEM, 0o600)
	}
	_ = email
	return block([]string{heading("HTTPS certificate"), "Let's Encrypt cert issued for " + domain, "restart panel to serve HTTPS on 0.0.0.0", "fix            ovm service restart"}), 0
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
	_ = os.MkdirAll(filepath.Dir(path), 0o755)
	if err := os.WriteFile(path, pemBytes, 0o600); err != nil {
		return nil, err
	}
	return key, nil
}
