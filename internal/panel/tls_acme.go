// Built-in ACME issuance and renewal. The panel owns the certificate: the
// installer (or `ovmanager tls acme`) issues the first pair through a
// standalone HTTP-01 listener, and this worker renews it before expiry.
//
// Renewal is driven by the certificate itself: the window is a third of the
// leaf's lifetime, capped at 30 days. That keeps a 90-day domain certificate
// on the familiar T-30d schedule while a short-lived IP certificate (about 6
// days) renews with roughly 2 days left instead of every daily tick.
package panel

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/anonysec/OVManager/internal/acme"
	"github.com/anonysec/OVManager/internal/telemetry"
)

const (
	acmeAccountKeyFile = "acme-account.pem"
	acmeIssueTimeout   = 5 * time.Minute
	acmeBootDelay      = 45 * time.Second
	acmeRenewEvery     = 24 * time.Hour
	acmeRetryEvery     = 4 * time.Hour
)

var (
	acmeWorkerOnce sync.Once
	acmeRetry      atomic.Bool
)

func acmeAccountKeyPath() string { return filepath.Join(tlsDir(), acmeAccountKeyFile) }

// acmeEnrollmentPath records the target this panel issued. Only an enrolled
// certificate is renewed; a custom or self-signed pair is left alone even when
// it is close to expiry.
func acmeEnrollmentPath() string { return filepath.Join(tlsDir(), "acme.json") }

type acmeEnrollment struct {
	Target string `json:"target"`
}

func acmeEnrollmentTarget() string {
	raw, err := os.ReadFile(acmeEnrollmentPath())
	if err != nil {
		return ""
	}
	var e acmeEnrollment
	if err := json.Unmarshal(raw, &e); err != nil {
		return ""
	}
	return strings.TrimSpace(e.Target)
}

func normalizeACMETarget(target string) string {
	target = strings.TrimSpace(target)
	if ip := net.ParseIP(target); ip != nil {
		return ip.String()
	}
	return strings.ToLower(strings.TrimSuffix(target, "."))
}

func saveACMEEnrollment(target string) {
	body, err := json.Marshal(acmeEnrollment{Target: normalizeACMETarget(target)})
	if err != nil {
		return
	}
	_ = atomicWrite(acmeEnrollmentPath(), append(body, '\n'), 0o600)
}

// acmeDirectoryURL overrides the CA directory (staging/test hook).
func acmeDirectoryURL() string { return strings.TrimSpace(envOrFile("AcmeDirectoryUrl")) }

// acmeHTTPPort is the standalone challenge listener, normally 80.
func acmeHTTPPort() int {
	if v := strings.TrimSpace(envOrFile("AcmeHttpPort")); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 && n <= 65535 {
			return n
		}
	}
	return 80
}

// loadOrCreateAccountKey reads DATA_DIR/tls/acme-account.pem or mints one.
// A corrupted file is replaced; a new key is simply a new account.
func loadOrCreateAccountKey() (crypto.Signer, error) {
	path := acmeAccountKeyPath()
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
		return nil, fmt.Errorf("acme account key generation failed: %w", err)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, err
	}
	pemBytes := pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	if err := atomicWrite(path, pemBytes, 0o600); err != nil {
		return nil, err
	}
	return key, nil
}

// runIssuance obtains a pair for target and activates it. Nothing is written
// unless the whole ACME flow succeeds.
func (h *Handler) runIssuance(ctx context.Context, target string) (*x509.Certificate, error) {
	signer, err := loadOrCreateAccountKey()
	if err != nil {
		return nil, err
	}
	profile := ""
	if net.ParseIP(target) != nil {
		profile = "shortlived"
	}
	ctxCall, cancel := context.WithTimeout(ctx, acmeIssueTimeout)
	defer cancel()
	res, err := acme.Issue(ctxCall, acme.Options{
		Domains:      []string{target},
		AccountKey:   signer,
		DirectoryURL: acmeDirectoryURL(),
		HTTPPort:     acmeHTTPPort(),
		Profile:      profile,
	})
	if err != nil {
		return nil, err
	}
	if len(res.AccountKeyPEM) > 0 {
		_ = atomicWrite(acmeAccountKeyPath(), res.AccountKeyPEM, 0o600)
	}
	parsed, err := writeManagedFiles(res.KeyPEM, res.CertPEM, "lets-encrypt")
	if err != nil {
		return nil, err
	}
	saveACMEEnrollment(target)
	return parsed, nil
}

// acmeRenewWindow is a third of the leaf lifetime, capped at 30 days and
// floored at one day so a very short-lived profile cannot renew in a loop.
func acmeRenewWindow(cert *x509.Certificate) time.Duration {
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

// acmeTarget is the name to renew: the first DNS SAN, then the first IP SAN,
// then the common name.
func acmeTarget(cert *x509.Certificate) string {
	if len(cert.DNSNames) > 0 {
		return cert.DNSNames[0]
	}
	if len(cert.IPAddresses) > 0 {
		return cert.IPAddresses[0].String()
	}
	return strings.TrimSpace(cert.Subject.CommonName)
}

// acmeTick is one worker run. It returns true when there is nothing to do or
// the renewal succeeded, and false when an issuance failed (the scheduler then
// retries sooner).
func (h *Handler) acmeTick(ctx context.Context) bool {
	target := acmeEnrollmentTarget()
	if target == "" {
		return true
	}
	certRaw, err := os.ReadFile(sslCertPath())
	if err != nil {
		return true // no managed pair yet; the installer issues the first one
	}
	block, _ := pem.Decode(certRaw)
	if block == nil || block.Type != "CERTIFICATE" {
		return true
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return true
	}
	if time.Until(cert.NotAfter) > acmeRenewWindow(cert) {
		return true
	}
	if normalizeACMETarget(acmeTarget(cert)) != normalizeACMETarget(target) {
		// The active pair is not the one this panel enrolled (a custom or
		// self-signed replacement); never overwrite it.
		return true
	}
	parsed, err := h.runIssuance(ctx, target)
	if err != nil {
		telemetry.RecordEvent(h.Svc.DB(), "tls_acme.renew", "error",
			"Automatic Let's Encrypt renewal failed for "+target,
			map[string]any{"target": target, "detail": err.Error()})
		return false
	}
	telemetry.RecordEvent(h.Svc.DB(), "tls_acme.renew", "info",
		"Let's Encrypt certificate renewed for "+target,
		map[string]any{"target": target, "expires_days": daysUntil(parsed)})
	return true
}

// startACMEWorker launches one renewal loop per process.
func (h *Handler) startACMEWorker() {
	acmeWorkerOnce.Do(func() {
		Run(context.Background(), []job{{
			name:  "acme worker",
			delay: acmeBootDelay,
			every: func() time.Duration {
				if acmeRetry.Load() {
					return acmeRetryEvery
				}
				return acmeRenewEvery
			},
			fn: func(ctx context.Context) {
				acmeRetry.Store(!h.acmeTick(ctx))
			},
		}})
	})
}
