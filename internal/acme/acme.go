// Package acme is a minimal ACME client for HTTP-01 certificate issuance,
// built on golang.org/x/crypto/acme (no new module dep). One call — Issue —
// runs the whole RFC 8555 flow against the Let's Encrypt production directory
// (or a test-only URL): register the account, create the order, answer the
// HTTP-01 challenges from a standalone listener that exists only for the
// duration of the run, finalize, and return a PEM chain plus the PEM key.
package acme

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"errors"
	"fmt"
	"net"
	"net/http"
	"strings"
	"time"

	"golang.org/x/crypto/acme"
)

// Options is one issuance.
type Options struct {
	// Domains goes into the order and the CSR (one or more DNS names).
	Domains []string
	// AccountKey, when empty, is generated (ECDSA P-256) and returned in
	// Result so the caller can persist it; the same key re-registers as an
	// existing account on re-issuance.
	AccountKey crypto.Signer
	// DirectoryURL overrides acme.LetsEncryptURL. Test/staging hook.
	DirectoryURL string
	// HTTPPort is the standalone HTTP-01 challenge listener's port, normally
	// 80 (the CA connects to the domain on port 80). 0 → ephemeral (tests).
	HTTPPort int
}

// Result is what a successful issuance leaves behind.
type Result struct {
	// AccountKeyPEM is the account key (PKCS#8) to persist for renewals.
	AccountKeyPEM []byte
	// KeyPEM is the new certificate's private key (PKCS#8).
	KeyPEM []byte
	// CertPEM is the full chain, leaf first.
	CertPEM []byte
	// Cert is the parsed leaf.
	Cert *x509.Certificate
}

// challengePrefix is where an HTTP-01 token must be reachable.
const challengePrefix = "/.well-known/acme-challenge/"

// Issue walks register → order → HTTP-01 → finalize → chain fetch. On any
// error the caller keeps nothing: nothing is written until the caller
// activates the returned pair.
func Issue(ctx context.Context, o Options) (*Result, error) {
	if len(o.Domains) == 0 {
		return nil, errors.New("acme: no domains given")
	}
	key := o.AccountKey
	if key == nil {
		generated, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			return nil, err
		}
		key = generated
	}

	// The challenge listener exists only while Issue runs: it answers any
	// .well-known/acme-challenge/<token> with this account's key
	// authorization, which is a pure function of the account key and the
	// token, so no state has to be shared with the ACME flow below.
	client, accountPEM, err := newClient(key, o.DirectoryURL)
	if err != nil {
		return nil, err
	}
	listener, err := net.Listen("tcp", fmt.Sprintf(":%d", o.HTTPPort))
	if err != nil {
		return nil, fmt.Errorf("acme: the standalone HTTP-01 listener could not bind port %d: %w",
			o.HTTPPort, err)
	}
	challenge := &http.Server{Handler: challengeHandler(client)}
	go func() { _ = challenge.Serve(listener) }()
	defer func() {
		ctxd, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = challenge.Shutdown(ctxd)
	}()

	if _, err := client.Register(ctx, &acme.Account{}, acme.AcceptTOS); err != nil {
		if !errors.Is(err, acme.ErrAccountAlreadyExists) {
			return nil, fmt.Errorf("acme: account registration failed: %w", err)
		}
	}

	ids := make([]acme.AuthzID, 0, len(o.Domains))
	for _, d := range o.Domains {
		ids = append(ids, acme.AuthzID{Type: "dns", Value: d})
	}
	order, err := client.AuthorizeOrder(ctx, ids)
	if err != nil {
		return nil, fmt.Errorf("acme: new order failed: %w", err)
	}
	for _, authzURL := range order.AuthzURLs {
		authz, err := client.GetAuthorization(ctx, authzURL)
		if err != nil {
			return nil, fmt.Errorf("acme: authorization failed: %w", err)
		}
		accepted := false
		for _, ch := range authz.Challenges {
			if ch.Type == "http-01" {
				if _, err := client.Accept(ctx, ch); err != nil {
					return nil, fmt.Errorf("acme: HTTP-01 challenge for %s: %w", authz.Identifier.Value, err)
				}
				accepted = true
			}
		}
		if !accepted {
			return nil, fmt.Errorf("acme: the CA offered no HTTP-01 challenge for %s", authz.Identifier.Value)
		}
		// The CA calls back on port 80; wait for the verdict (invalid →
		// carries the CA's problem detail).
		if _, err := client.WaitAuthorization(ctx, authzURL); err != nil {
			return nil, fmt.Errorf("acme: the HTTP-01 challenge for %s was not satisfied: %w",
				authz.Identifier.Value, err)
		}
	}
	order, err = client.WaitOrder(ctx, order.URI)
	if err != nil {
		var orderErr *acme.OrderError
		if errors.As(err, &orderErr) && orderErr.Problem != nil {
			return nil, fmt.Errorf("acme: %s", orderErr.Problem.Detail)
		}
		return nil, fmt.Errorf("acme: order wait failed: %w", err)
	}

	certKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, err
	}
	csrDER, err := x509.CreateCertificateRequest(rand.Reader, &x509.CertificateRequest{
		Subject:  pkix.Name{CommonName: o.Domains[0]},
		DNSNames: o.Domains,
	}, certKey)
	if err != nil {
		return nil, err
	}
	chain, _, err := client.CreateCertFromOrder(ctx, order, csrDER, true)
	if err != nil {
		return nil, fmt.Errorf("acme: certificate finalization failed: %w", err)
	}

	var certPEM []byte
	for _, der := range chain {
		certPEM = append(certPEM, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})...)
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(certKey)
	if err != nil {
		return nil, err
	}
	leaf, err := x509.ParseCertificate(chain[0])
	if err != nil {
		return nil, fmt.Errorf("acme: the issued certificate is not parseable: %w", err)
	}
	return &Result{
		AccountKeyPEM: accountPEM,
		KeyPEM:        pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}),
		CertPEM:       certPEM,
		Cert:          leaf,
	}, nil
}

// newClient builds the client and serializes the account key (always — the
// caller decides whether to persist it).
func newClient(key crypto.Signer, directoryURL string) (*acme.Client, []byte, error) {
	client := &acme.Client{Key: key}
	if directoryURL != "" {
		client.DirectoryURL = directoryURL
	}
	keyDER, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		return nil, nil, err
	}
	return client, pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}), nil
}

// challengeHandler serves the HTTP-01 responses over the standalone listener.
func challengeHandler(client *acme.Client) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc(challengePrefix, func(w http.ResponseWriter, r *http.Request) {
		resp, err := client.HTTP01ChallengeResponse(strings.TrimPrefix(r.URL.Path, challengePrefix))
		if err != nil {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "text/plain")
		_, _ = w.Write([]byte(resp))
	})
	return mux
}

// RenewDue reports whether a managed pair needs renewal: no pair at all, an
// unparseable one (treat as broken, not as fine), or the leaf expires within
// windowDays.
func RenewDue(keyPEM, certPEM []byte, windowDays int) bool {
	if len(keyPEM) == 0 || len(certPEM) == 0 {
		return true
	}
	if block, _ := pem.Decode(keyPEM); block == nil {
		return true // the key half is not even PEM: the pair is broken
	}
	block, _ := pem.Decode(certPEM)
	if block == nil || block.Type != "CERTIFICATE" {
		return true
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return true
	}
	return cert.NotAfter.Before(time.Now().AddDate(0, 0, windowDays))
}
