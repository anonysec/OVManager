// Built-in ACME issuance (Task 1 of the post-cutover feature gaps): a thin
// panel wrapper around internal/acme so a Let's Encrypt certificate can be
// obtained without acme.sh on the host. Production flow: POST /api/tls/acme
// runs the HTTP-01 flow against a standalone listener on port 80 (env
// OVM_ACME_HTTP_PORT), then activates the pair through writeManagedFiles —
// the same transactional, previous-pair-retaining pipeline as every other
// certificate change. A daily worker renews at T-30 days and, when the
// installer wires OVM_ACME_DOMAIN, performs boot-time issuance (retry on the
// next daily tick; or the operator hits the endpoint from Settings → HTTPS).
//
// Fail-closed parity with migrate_legacy_tls: issuance failures write
// nothing — the previous pair stays intact and the error carries ACME's own
// message.
package panel

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/acme"
	"github.com/anonysec/OVManager/go/internal/telemetry"
)

// acmeAccountKeyFile is the persisted ACME account key, inside DATA_DIR/tls
// (atomicWrite's allowed region).
const acmeAccountKeyFile = "acme-account.pem"

func acmeAccountKeyPath() string { return filepath.Join(tlsDir(), acmeAccountKeyFile) }

// acmeWindowDays is the renewal threshold: re-issue when the leaf is within
// 30 days of expiry.
const acmeWindowDays = 30

// acmeHTTPIssueTimeout bounds one built-in issuance; the LE flow with one
// round trip back for the HTTP-01 validation fits comfortably.
const acmeHTTPIssueTimeout = 180 * time.Second

// acmeDirectoryURL overrides the CA directory (test/staging hook).
func acmeDirectoryURL() string { return strings.TrimSpace(envOrFile("OVM_ACME_DIRECTORY_URL")) }

// acmeHTTPPort is the standalone challenge port. The installer grants
// CAP_NET_BIND_SERVICE for the :80 bind; anything already holding the port
// fails the bind and the error surfaces (fail-closed).
func acmeHTTPPort() int {
	if v := envOrFile("OVM_ACME_HTTP_PORT"); v != "" {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil && n > 0 && n <= 65535 {
			return n
		}
	}
	return 80
}

// acmeDomain is the enrolled DNS name: the env key the installer wires, then
// the saved settings column.
func (h *Handler) acmeDomain() string {
	if v := strings.TrimSpace(envOrFile("OVM_ACME_DOMAIN")); v != "" && validateDomain(v) {
		return v
	}
	if v := strings.TrimSpace(h.settings().strOr("acme_domain")); v != "" && validateDomain(v) {
		return v
	}
	return ""
}

// acmeIssueRequest is POST /api/tls/acme's body.
type acmeIssueRequest struct {
	Domain *string `json:"domain"`
	Email  *string `json:"email"`
}

type acmeIssueResult struct {
	parsed      *x509.Certificate
	expiresDays int
}

// tlsACMEIssue runs one issuance synchronously (like tlsRenew): request →
// listener + ACME flow → transactional activation → settings + audit event.
func (h *Handler) tlsACMEIssue(w http.ResponseWriter, r *http.Request) {
	var payload acmeIssueRequest
	if !decodeBody(w, r, &payload) {
		return
	}
	domain := ""
	if payload.Domain != nil {
		domain = strings.TrimSpace(*payload.Domain)
	}
	if domain == "" || !validateDomain(domain) {
		envelope(w, false, "That domain name is not valid. Use letters, digits, dots and hyphens only.", nil)
		return
	}
	email := ""
	if payload.Email != nil {
		email = strings.TrimSpace(*payload.Email)
	}
	if email != "" && !validateEmail(email) {
		envelope(w, false, "That email address is not valid.", nil)
		return
	}

	// Idempotency: a managed pair covering the domain, a month+ from expiry,
	// stays until the daily worker. Prevents a double-click from hammering
	// the CA with a redundant order.
	if cert, err := loadCertificate(sslCertPath()); err == nil && cert != nil &&
		certMatchesName(cert, domain) && daysUntil(cert) > acmeWindowDays {
		envelope(w, true, fmt.Sprintf("A certificate for %s covers the domain and is still valid (%d days left); renewal is automatic within the 30-day window.", domain, daysUntil(cert)),
			map[string]any{"restart_required": false, "skipped": true,
				"expires_days": daysUntil(cert), "domain": domain})
		return
	}

	res, err := h.runIssuance(r.Context(), domain)
	if err != nil {
		telemetry.RecordEvent(h.Svc.DB(), "tls_acme", "error",
			"Let's Encrypt certificate issuance failed for "+domain,
			map[string]any{"target": domain, "detail": err.Error()})
		envelope(w, false,
			fmt.Sprintf("Let's Encrypt certificate issuance failed: %v. The previous certificate is still active.", err),
			map[string]any{"restart_required": false})
		return
	}
	// The pair is active on disk; make sure a settings row exists before
	// pointing the SSL_* columns at it (readSettings seeds the row — a fresh
	// install has none, and a 0-row UPDATE would silently pass).
	readSettings(h.Svc.DB())
	if err := setColumns(h.Svc.DB(), map[string]any{
		"ssl_cert_file": sslCertPath(), "ssl_key_file": sslKeyPath(),
	}); err != nil {
		// The pair is active on disk; only the settings row failed.
		envelope(w, true, "The certificate was installed, but the TLS settings row could not be updated. "+restartHint,
			map[string]any{"restart_required": true, "cert_path": sslCertPath(),
				"key_path": sslKeyPath(), "domain": domain, "expires_days": res.expiresDays})
		return
	}
	telemetry.RecordEvent(h.Svc.DB(), "tls_acme", "info",
		"Let's Encrypt certificate installed for "+domain,
		map[string]any{"target": domain, "expires_days": res.expiresDays})
	envelope(w, true, fmt.Sprintf("Let's Encrypt certificate for %s installed. %s", domain, restartHint),
		map[string]any{
			"restart_required": true, "cert_path": sslCertPath(), "key_path": sslKeyPath(),
			"domain": domain, "expires_days": res.expiresDays,
		})
}

// runIssuance serializes issuances (endpoint + worker share this mutex),
// loads-or-mints the account key before any ACME traffic so the HTTP-01 wait
// can always be honoured for re-issuances, then activates the pair through
// writeManagedFiles. On any error nothing is written.
func (h *Handler) runIssuance(ctx context.Context, domain string) (*acmeIssueResult, error) {
	h.acmeMu.Lock()
	defer h.acmeMu.Unlock()

	signer, err := loadOrCreateAccountKey()
	if err != nil {
		return nil, err
	}
	options := acme.Options{
		Domains:      []string{domain},
		AccountKey:   signer,
		DirectoryURL: acmeDirectoryURL(),
		HTTPPort:     acmeHTTPPort(),
	}
	ctxCall, cancel := context.WithTimeout(ctx, acmeHTTPIssueTimeout)
	defer cancel()
	res, err := acme.Issue(ctxCall, options)
	if err != nil {
		return nil, err
	}
	parsed, err := writeManagedFiles(res.KeyPEM, res.CertPEM, "lets-encrypt")
	if err != nil {
		return nil, err
	}
	return &acmeIssueResult{parsed: parsed, expiresDays: daysUntil(parsed)}, nil
}

// loadOrCreateAccountKey reads DATA_DIR/tls/acme-account.pem or mints a new
// one and persists it. A corrupted file is replaced (LE collapses accounts by
// key, so a fresh key is simply a new account), never fatal.
func loadOrCreateAccountKey() (crypto.Signer, error) {
	path := acmeAccountKeyPath()
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

// --- renewal worker (single goroutine, daily tick) ---

// acmeRenewInterval is the daily check. acmeRetryInterval is the shorter
// re-attempt after a FAILED issuance (a flaky network should not cost the
// certificate a whole day). acmeBootCheckDelay leaves the panel time to
// settle before the OVM_ACME_DOMAIN boot issuance.
const (
	acmeRenewInterval  = 24 * time.Hour
	acmeRetryInterval  = 4 * time.Hour
	acmeBootCheckDelay = 45 * time.Second
)

var acmeWorkerOnce sync.Once

// startACMEWorker launches the renewal loop once per process. Idempotent,
// so Mount can call it unconditionally.
func (h *Handler) startACMEWorker() {
	acmeWorkerOnce.Do(func() {
		go func() {
			defer func() { recover() }()
			time.Sleep(acmeBootCheckDelay)
			for {
				// The sleep stays OUTSIDE the guard: a panic must not turn
				// this into a hot spin.
				renewed := false
				runGuarded("acme worker", func() { renewed = h.acmeMaintenance() })
				if renewed {
					time.Sleep(acmeRenewInterval)
				} else {
					// A issuance just failed (or panicked): retry sooner
					// instead of waiting out the daily tick.
					time.Sleep(acmeRetryInterval)
				}
			}
		}()
	})
}

// acmeMaintenance is one worker tick: enrolled domain required, renewal
// only when RenewDue says so. It reports whether the tick ended without
// an issuance failure (no domain, nothing due, or success). Failures are
// audit events, synced after the next tick (or the endpoint).
func (h *Handler) acmeMaintenance() bool {
	domain := h.acmeDomain()
	if domain == "" {
		return true
	}
	keyRaw, _ := os.ReadFile(sslKeyPath())
	certRaw, _ := os.ReadFile(sslCertPath())
	if !acme.RenewDue(keyRaw, certRaw, acmeWindowDays) {
		return true
	}
	ctx, cancel := context.WithTimeout(context.Background(), acmeHTTPIssueTimeout+10*time.Second)
	defer cancel()
	res, err := h.runIssuance(ctx, domain)
	if err != nil {
		telemetry.RecordEvent(h.Svc.DB(), "tls_acme.renew", "error",
			"Automatic Let's Encrypt renewal failed for "+domain,
			map[string]any{"target": domain, "detail": err.Error()})
		return false
	}
	readSettings(h.Svc.DB())
	_ = setColumns(h.Svc.DB(), map[string]any{
		"ssl_cert_file": sslCertPath(), "ssl_key_file": sslKeyPath(),
	})
	telemetry.RecordEvent(h.Svc.DB(), "tls_acme.renew", "info",
		"Let's Encrypt certificate renewed for "+domain,
		map[string]any{"target": domain, "expires_days": daysUntil(res.parsed)})
	return true
}
