// Task 1 of the post-cutover feature gaps: ACME + one-click TLS. The panel
// gains a built-in ACME client (no acme.sh on the host) behind POST
// /api/tls/acme, a standalone HTTP-01 challenge listener that lives only for
// the duration of an issuance, and a renewal worker (T-30d). The end-to-end
// flow runs against a minimal RFC 8555 stub directory, so every step the
// production client uses — account registration, new-order, HTTP-01 token
// serving, finalize, PEM chain download — is exercised.
package tests

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/acme"
	xacme "golang.org/x/crypto/acme"
)

// fakeACME is a minimal ACME server stub: just enough of RFC 8555 to walk
// x/crypto/acme's client through register → order → HTTP-01 → finalize →
// certificate fetch.
type fakeACME struct {
	t    *testing.T
	srv  *httptest.Server
	base string

	domain  string
	leafPEM string // the "issued" chain (single certificate), minted at finalize

	caKey  *ecdsa.PrivateKey
	caCert []byte

	// challengeBase is where the stub fetches HTTP-01 tokens from the
	// client's standalone listener (loopback <port> in tests).
	challengeBase string
	// token served as the HTTP-01 challenge.
	token string
	// verifyChallenge decides, on the fetched token response, whether the
	// authorization flips to valid. The response *is* the key authorization
	// (token.thumbprint); the test re-derives it from the account key on disk.
	verifyChallenge func(keyAuth string) bool

	mu           sync.Mutex
	authzValid   bool
	issuedCount  int    // certificate fetches served
	orderReplies int    // POST /new-order attempts
	orderCode    int    // failure injection: status for POST /new-order
	challengeReq string // what the challenge listener returned; "" when not fetched
}

// newFakeACME starts the stub and prepares an "issued" pair for domain.
func newFakeACME(t *testing.T, domain string) *fakeACME {
	t.Helper()
	f := &fakeACME{
		t:      t,
		domain: domain,
		token:  "stub-token-" + fmt.Sprint(time.Now().UnixNano()),
	}
	// The stub CA signs the leaf it "issues" on finalize.
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("stub CA key: %v", err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "stub CA"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("stub CA cert: %v", err)
	}
	f.caKey, f.caCert = key, der
	mux := http.NewServeMux()
	mux.HandleFunc("/dir", f.dir)
	mux.HandleFunc("/nonce", f.nonce)
	mux.HandleFunc("/acct/1", f.account)
	mux.HandleFunc("/order/1", f.order)
	mux.HandleFunc("/order", f.order)
	mux.HandleFunc("/authz/1", f.authz)
	mux.HandleFunc("/chal/1", f.challenge)
	mux.HandleFunc("/final/1", f.finalize)
	mux.HandleFunc("/cert/1", f.cert)
	f.srv = httptest.NewServer(mux)
	t.Cleanup(f.srv.Close)
	f.base = f.srv.URL
	return f
}

func (f *fakeACME) authzStatus() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.authzValid {
		return "valid"
	}
	return "pending"
}

func (f *fakeACME) dir(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"newNonce":%q,"newAccount":%q,"newOrder":%q}`+"\n",
		f.base+"/nonce", f.base+"/acct/1", f.base+"/order")
}

func (f *fakeACME) nonce(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Replay-Nonce", "stub-nonce")
	w.WriteHeader(http.StatusNoContent)
}

func (f *fakeACME) account(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Replay-Nonce", "stub-nonce")
	w.Header().Set("Location", f.base+"/acct/1")
	w.WriteHeader(http.StatusCreated)
	fmt.Fprintln(w, `{"status":"valid"}`)
}

func (f *fakeACME) order(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	w.Header().Set("Replay-Nonce", "stub-nonce")
	f.orderReplies++
	if f.orderCode != 0 {
		w.Header().Set("Content-Type", "application/problem+json")
		w.WriteHeader(f.orderCode)
		fmt.Fprint(w, `{"type":"urn:ietf:params:acme:error:serverInternal","detail":"stub refuses"}`)
		return
	}
	status := "pending"
	if f.authzValid {
		status = "ready"
	}
	if r.Method == http.MethodPost && r.URL.Path == "/order" {
		// new order: 201 with Location.
		w.Header().Set("Location", f.base+"/order/1")
		w.WriteHeader(http.StatusCreated)
	} else {
		// poll (post-as-GET or GET): 200, no Location.
		w.WriteHeader(http.StatusOK)
	}
	fmt.Fprintf(w, `{"status":%q,"identifiers":[{"type":"dns","value":%q}],`+
		`"authorizations":[%q],"finalize":%q}`+"\n",
		status, f.domain, f.base+"/authz/1", f.base+"/final/1")
}

func (f *fakeACME) authz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Replay-Nonce", "stub-nonce")
	w.Header().Set("Content-Type", "application/json")
	fmt.Fprintf(w, `{"status":%q,"identifier":{"type":"dns","value":%q},`+
		`"challenges":[{"type":"http-01","url":%q,"token":%q}]}`+"\n",
		f.authzStatus(), f.domain, f.base+"/chal/1", f.token)
}

// challenge is the client's Accept POST; the stub verifies the HTTP-01 token
// against the client's standalone listener, then marks the authorization valid.
func (f *fakeACME) challenge(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	alreadyValid := f.authzValid
	f.mu.Unlock()
	if !alreadyValid {
		go f.validate()
	}
	w.Header().Set("Replay-Nonce", "stub-nonce")
	fmt.Fprintf(w, `{"type":"http-01","url":%q,"token":%q,"status":"processing"}`, f.base+"/chal/1", f.token)
}

// validate plays the CA: GET the expected HTTP-01 response from the client's
// standalone listener and hand it to the test hook.
func (f *fakeACME) validate() {
	if f.challengeBase == "" {
		f.mu.Lock()
		f.authzValid = true
		f.mu.Unlock()
		return
	}
	client := &http.Client{Timeout: 10 * time.Second}
	var body string
	for i := 0; i < 25; i++ {
		res, err := client.Get(f.challengeBase + "/.well-known/acme-challenge/" + f.token)
		if err == nil {
			raw, _ := io.ReadAll(res.Body)
			res.Body.Close()
			body = strings.TrimSpace(string(raw))
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	f.mu.Lock()
	f.challengeReq = body
	if f.verifyChallenge == nil || f.verifyChallenge(body) {
		f.authzValid = true
	}
	f.mu.Unlock()
}

func (f *fakeACME) finalize(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	ready := f.authzValid
	f.mu.Unlock()
	w.Header().Set("Replay-Nonce", "stub-nonce")
	if !ready {
		fmt.Fprintf(w, `{"status":"pending","identifiers":[{"type":"dns","value":%q}],`+
			`"authorizations":[%q],"finalize":%q}`+"\n",
			f.domain, f.base+"/authz/1", f.base+"/final/1")
		return
	}
	// Mint the leaf against the CSR's public key, the way a real CA signs.
	certPEM, err := f.mintLeaf(r)
	if err != nil {
		f.t.Errorf("stub finalize: %v", err)
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	f.mu.Lock()
	f.leafPEM = certPEM
	f.mu.Unlock()
	fmt.Fprintf(w, `{"status":"valid","certificate":%q}`+"\n", f.base+"/cert/1")
}

// mintLeaf unwraps the client's JWS payload, decodes the CSR and signs a
// 90-day leaf for its subject/SANs with the stub CA.
func (f *fakeACME) mintLeaf(r *http.Request) (string, error) {
	var jws struct {
		Payload string `json:"payload"`
	}
	if err := json.NewDecoder(r.Body).Decode(&jws); err != nil {
		return "", fmt.Errorf("JWS body: %w", err)
	}
	payload, err := base64.RawURLEncoding.DecodeString(jws.Payload)
	if err != nil {
		return "", fmt.Errorf("JWS payload: %w", err)
	}
	var req struct {
		CSR string `json:"csr"`
	}
	if err := json.Unmarshal(payload, &req); err != nil {
		return "", fmt.Errorf("finalize payload: %w", err)
	}
	csrDER, err := base64.RawURLEncoding.DecodeString(req.CSR)
	if err != nil {
		return "", fmt.Errorf("csr b64: %w", err)
	}
	csr, err := x509.ParseCertificateRequest(csrDER)
	if err != nil {
		return "", fmt.Errorf("csr parse: %w", err)
	}
	leaf := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      csr.Subject,
		DNSNames:     csr.DNSNames,
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(90 * 24 * time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, leaf, f.caCertHolder(), csr.PublicKey, f.caKey)
	if err != nil {
		return "", err
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})), nil
}

func (f *fakeACME) caCertHolder() *x509.Certificate {
	cert, err := x509.ParseCertificate(f.caCert)
	if err != nil {
		return &x509.Certificate{}
	}
	return cert
}

func (f *fakeACME) cert(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.issuedCount++
	pemText := f.leafPEM
	f.mu.Unlock()
	w.Header().Set("Content-Type", "application/pem-certificate-chain")
	fmt.Fprint(w, pemText)
}

// reservePort grabs a loopback port and releases it for the challenge listener.
func reservePort(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve port: %v", err)
	}
	_, port, _ := net.SplitHostPort(l.Addr().String())
	if err := l.Close(); err != nil {
		t.Fatalf("release port: %v", err)
	}
	return port
}

// acmeEnv wires one panel env + one stub CA + a throwaway challenge port.
func acmeEnv(t *testing.T) (*panelEnv, *fakeACME) {
	t.Helper()
	env := newPanelEnv(t)
	dir := filepath.Join(env.dataDir, "tls")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("tls dir: %v", err)
	}
	f := newFakeACME(t, "panel.example.test")
	port := reservePort(t)
	f.challengeBase = "http://127.0.0.1:" + port
	t.Setenv("OVM_ACME_DIRECTORY_URL", f.base+"/dir")
	t.Setenv("OVM_ACME_HTTP_PORT", port)
	return env, f
}

// acmeKeyAuth re-derives the expected HTTP-01 response (token.thumbprint) from
// an account key PEM — exactly what the standalone listener must serve.
func acmeKeyAuth(accountKeyPEM []byte, token string) (string, error) {
	block, _ := pem.Decode(accountKeyPEM)
	if block == nil {
		return "", fmt.Errorf("no PEM block in account key")
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return "", err
	}
	signer, ok := key.(crypto.Signer)
	if !ok {
		return "", fmt.Errorf("account key is not a signer")
	}
	return (&xacme.Client{Key: signer}).HTTP01ChallengeResponse(token)
}

// TestACMEEndToEnd issues a real (stub-CA) certificate through the panel
// endpoint: account key persisted first, the HTTP-01 token served by the
// standalone listener, the pair written on the declared paths, the previous
// pair retained, the SSL_* settings columns set, and an audit event recorded.
func TestACMEEndToEnd(t *testing.T) {
	env, f := acmeEnv(t)
	keyDeclared, certDeclared := declaredPaths(t, env.dataDir)
	accountKeyPath := filepath.Join(env.dataDir, "tls", "acme-account.pem")

	// A running pair is already in place, as if the panel had a self-signed
	// certificate — the issued pair must not clobber it silently: the old pair
	// moves to previous-* and stays readable.
	oldKey, oldCert := mintPair(t, "old.example.test")
	if err := os.MkdirAll(filepath.Dir(keyDeclared), 0o755); err != nil {
		t.Fatalf("declared dir: %v", err)
	}
	if err := os.WriteFile(keyDeclared, []byte(oldKey), 0o600); err != nil {
		t.Fatalf("seed key: %v", err)
	}
	if err := os.WriteFile(certDeclared, []byte(oldCert), 0o644); err != nil {
		t.Fatalf("seed cert: %v", err)
	}

	// The hook re-derives the expected key authorization from the account key
	// the panel persists before it starts the ACME flow. Small retry: the hook
	// fires inside the issuance request.
	f.verifyChallenge = func(got string) bool {
		for i := 0; i < 50; i++ {
			raw, err := os.ReadFile(accountKeyPath)
			if err == nil {
				want, err := acmeKeyAuth(raw, f.token)
				if err == nil {
					return got == want
				}
			}
			time.Sleep(100 * time.Millisecond)
		}
		t.Errorf("account key never usable while validating the challenge")
		return false
	}

	res, body := doJSON(t, "POST", env.srv.URL+"/api/tls/acme", env.token,
		map[string]any{"domain": f.domain})
	if res.StatusCode != 200 || body["success"] != true {
		t.Fatalf("POST /api/tls/acme = %d %v", res.StatusCode, body)
	}
	data, _ := body["data"].(map[string]any)
	if data["restart_required"] != true {
		t.Errorf("data.restart_required = %v, want true", data["restart_required"])
	}
	if days, _ := data["expires_days"].(float64); days < 89 {
		t.Errorf("data.expires_days = %v, want ~90", data["expires_days"])
	}

	// The challenge listener served the exact key authorization of the
	// persisted account key.
	if f.challengeReq == "" {
		t.Fatalf("the stub CA never fetched the HTTP-01 token")
	}
	raw, err := os.ReadFile(accountKeyPath)
	if err != nil {
		t.Fatalf("account key not persisted: %v", err)
	}
	want, err := acmeKeyAuth(raw, f.token)
	if err != nil {
		t.Fatalf("account key parse: %v", err)
	}
	if f.challengeReq != want {
		t.Fatalf("challenge response = %q, want the account key authorization %q", f.challengeReq, want)
	}

	// The issued pair replaced the old one; the old pair is retained.
	newKeyRaw, err := os.ReadFile(keyDeclared)
	if err != nil {
		t.Fatalf("declared key: %v", err)
	}
	if string(newKeyRaw) == oldKey {
		t.Fatalf("the declared key was not replaced")
	}
	certRaw, err := os.ReadFile(certDeclared)
	if err != nil {
		t.Fatalf("declared cert: %v", err)
	}
	block, _ := pem.Decode(certRaw)
	if block == nil {
		t.Fatalf("declared cert is not PEM")
	}
	parsed, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatalf("issued cert parse: %v", err)
	}
	if len(parsed.DNSNames) != 1 || parsed.DNSNames[0] != f.domain {
		t.Errorf("issued cert SANs = %v, want [%s]", parsed.DNSNames, f.domain)
	}
	for _, path := range []string{filepath.Join(env.dataDir, "tls", "previous-privkey.pem"),
		filepath.Join(env.dataDir, "tls", "previous-fullchain.pem")} {
		if _, err := os.Stat(path); err != nil {
			t.Errorf("previous pair not retained at %s: %v", path, err)
		}
	}

	// The SSL_* settings columns now name the declared paths.
	var certCol, keyCol string
	if err := env.conn.QueryRow(`SELECT ssl_cert_file, ssl_key_file FROM settings LIMIT 1`).
		Scan(&certCol, &keyCol); err != nil || certCol != certDeclared || keyCol != keyDeclared {
		t.Errorf("settings columns = %s/%s (err=%v), want %s/%s", certCol, keyCol, err, certDeclared, keyDeclared)
	}

	// Audit trail: one event with the domain as target.
	var noop string
	if err := env.conn.QueryRow(`SELECT target FROM audit_logs WHERE action = 'tls_acme' AND target = ?`,
		f.domain).Scan(&noop); err != nil {
		t.Fatalf("no tls_acme audit event for %q: %v", f.domain, err)
	}
}

// TestACMEFailsClosed: when the CA refuses, nothing is written, the previous
// pair is untouched, and ACME's message is surfaced.
func TestACMEFailsClosed(t *testing.T) {
	env, f := acmeEnv(t)
	keyDeclared, certDeclared := declaredPaths(t, env.dataDir)
	f.orderCode = 400

	sKey, sCert := mintPair(t, "keep.example.test")
	if err := os.MkdirAll(filepath.Dir(keyDeclared), 0o755); err != nil {
		t.Fatalf("declared dir: %v", err)
	}
	os.WriteFile(keyDeclared, []byte(sKey), 0o600)
	os.WriteFile(certDeclared, []byte(sCert), 0o644)

	res, body := doJSON(t, "POST", env.srv.URL+"/api/tls/acme", env.token,
		map[string]any{"domain": f.domain})
	if body["success"] != false {
		t.Fatalf("POST /api/tls/acme = %d %v, want failure", res.StatusCode, body)
	}
	msg, _ := body["msg"].(string)
	if !strings.Contains(msg, "Let's Encrypt") {
		t.Errorf("msg = %q, want the Let's Encrypt wording", msg)
	}
	if !strings.Contains(msg, "stub refuses") {
		t.Errorf("msg = %q, want ACME's own message carried through", msg)
	}
	if raw, _ := os.ReadFile(certDeclared); string(raw) != sCert {
		t.Errorf("the declared certificate was touched on failure")
	}
	if raw, _ := os.ReadFile(keyDeclared); string(raw) != sKey {
		t.Errorf("the declared key was touched on failure")
	}
}

// TestACMEValidatesDomainBeforeContactingTheCA: a bad domain is refused
// without a single request to the CA.
func TestACMEValidatesDomainBeforeContactingTheCA(t *testing.T) {
	env, f := acmeEnv(t)
	res, body := doJSON(t, "POST", env.srv.URL+"/api/tls/acme", env.token,
		map[string]any{"domain": "bad_domain.example"})
	if body["success"] != false {
		t.Fatalf("bad domain accepted: %d %v", res.StatusCode, body)
	}
	if f.orderReplies != 0 {
		t.Errorf("the CA was contacted %d times behind validation", f.orderReplies)
	}
}

// TestACMEIssue is the direct unit probe of internal/acme against the stub.
func TestACMEIssue(t *testing.T) {
	f := newFakeACME(t, "unit.example.test")
	port := reservePort(t)
	f.challengeBase = "http://127.0.0.1:" + port
	f.verifyChallenge = func(got string) bool { return got != "" }

	o := acme.Options{Domains: []string{"unit.example.test"}}
	o.DirectoryURL = f.base + "/dir"
	hp, _ := strconv.Atoi(port)
	o.HTTPPort = hp
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	got, err := acme.Issue(ctx, o)
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	if got.Cert == nil || got.Cert.NotAfter.Before(time.Now()) {
		t.Fatalf("cert = %v", got.Cert)
	}
	if len(got.Cert.DNSNames) != 1 || got.Cert.DNSNames[0] != "unit.example.test" {
		t.Errorf("SANs = %v", got.Cert.DNSNames)
	}
}

// TestACMERenewDue reports whether a managed pair needs a T-30d renewal —
// the predicate the daily worker calls.
func TestACMERenewDue(t *testing.T) {
	keyPEM, certPEM := mintPair(t, "fresh.example.test")
	if acme.RenewDue([]byte(keyPEM), []byte(certPEM), 30) {
		t.Errorf("a fresh 90-day certificate within the window is renewDue")
	}
	if !acme.RenewDue([]byte(keyPEM), nil, 30) {
		t.Errorf("a missing certificate half is renewDue")
	}
	if !acme.RenewDue([]byte("not a pem"), []byte(certPEM), 30) {
		t.Errorf("an unparseable certificate is renewDue")
	}
	if !acme.RenewDue([]byte(keyPEM), []byte(certPEM), 400) {
		t.Errorf("a 90-day certificate inside a 400-day window is renewDue")
	}
}
