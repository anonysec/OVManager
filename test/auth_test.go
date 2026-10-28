package tests

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/anonysec/OVManager/go/internal/auth"
)

// TestAuthVerifiesHash is the hash-parity guard: a hash written by the
// backend (auth/hash, $2b$12$) must verify in Go.
func TestAuthVerifiesHash(t *testing.T) {
	if !auth.VerifyPassword(knownPassword, bcryptHash) {
		t.Fatalf("Go could not verify the bcrypt hash")
	}
	if auth.VerifyPassword("wrong", bcryptHash) {
		t.Errorf("wrong password verified against hash")
	}
	if auth.VerifyPassword(knownPassword, "") {
		t.Errorf("empty hash must never verify")
	}
	// Go-minted hashes are $2b$12$ and round-trip, matching the policy.
	h, err := auth.HashPassword(knownPassword)
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}
	if h[:4] != "$2b$" || h[4:6] != "12" {
		t.Errorf("hash prefix = %q, want $2b$12$...", h[:7])
	}
	if !auth.VerifyPassword(knownPassword, h) {
		t.Errorf("Go hash did not verify in Go")
	}
	if !auth.NeedsRehash("$2a$10$abcdefghijklmnopqrstuv") {
		t.Errorf("legacy $2a$10$ hash must need a rehash")
	}
	if auth.NeedsRehash(h) {
		t.Errorf("fresh hash needs rehash, want false")
	}
}

// TestAuthLoginSuccess mirrors backend/auth login: token envelope plus
// the ovm_session cookie (max-age = SESSION_MAX_SECONDS, HttpOnly, Lax, "/").
func TestAuthLoginSuccess(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)

	res := postForm(t, srv.URL, "/api/login", url.Values{"username": {"admin"}, "password": {knownPassword}})
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want 200", res.StatusCode)
	}
	var got map[string]any
	if err := json.NewDecoder(res.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["token_type"] != "bearer" || got["role"] != "owner" || got["username"] != "admin" {
		t.Errorf("envelope = %v", got)
	}
	if v, ok := got["refresh_token"]; !ok || v != nil {
		t.Errorf("refresh_token = %v, want null present", v)
	}
	token, _ := got["access_token"].(string)
	if len(token) != 43 { // token_urlsafe(32) → 43 chars
		t.Errorf("token len = %d (%q), want 43", len(token), token)
	}
	// Exactly the five login keys.
	if len(got) != 5 {
		t.Errorf("keys = %v, want 5", got)
	}
	cookie := res.Header.Get("ovm_session")
	_ = cookie
	var found *http.Cookie
	for _, c := range res.Cookies() {
		if c.Name == "ovm_session" {
			found = c
		}
	}
	if found == nil {
		t.Fatalf("no ovm_session cookie")
	}
	if found.Value != token || !found.HttpOnly || found.Path != "/" ||
		found.SameSite != http.SameSiteLaxMode || found.MaxAge != 604800 {
		t.Errorf("cookie = %+v", found)
	}
	// Only the SHA-256 digest of the raw token is stored.
	sum := sha256.Sum256([]byte(token))
	var stored string
	if err := conn.QueryRow(`SELECT token_hash FROM sessions WHERE username='admin'`).Scan(&stored); err != nil {
		t.Fatalf("session row: %v", err)
	}
	if stored != hex.EncodeToString(sum[:]) {
		t.Errorf("stored hash = %s, want sha256(raw)", stored)
	}
}

// TestAuthLoginWrongPassword mirrors the 401 shape (backend).
func TestAuthLoginWrongPassword(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)

	res := postForm(t, srv.URL, "/api/login", url.Values{"username": {"admin"}, "password": {"nope"}})
	defer res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", res.StatusCode)
	}
	if h := res.Header.Get("WWW-Authenticate"); h != "Bearer" {
		t.Errorf("WWW-Authenticate = %q, want Bearer", h)
	}
	var got map[string]any
	_ = json.NewDecoder(res.Body).Decode(&got)
	if got["detail"] != "The username or password is incorrect" {
		t.Errorf("detail = %v", got["detail"])
	}
}

// TestAuthLoginUnknownNonOwnerNeverAuthenticates: only the is_owner row is a
// credential (backend/auth authenticate_user).
func TestAuthLoginUnknownNonOwner(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES ('second', ?, 0)`, bcryptHash); err != nil {
		t.Fatal(err)
	}
	srv := newServer(t, conn, dir)
	res := postForm(t, srv.URL, "/api/login", url.Values{"username": {"second"}, "password": {knownPassword}})
	defer res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("non-owner login status = %d, want 401", res.StatusCode)
	}
}

// TestAuthLoginLockout mirrors the in-memory rate limiter's 429 + Retry-After.
func TestAuthLoginLockout(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)
	var res *http.Response
	for i := 0; i < 5; i++ {
		res = postForm(t, srv.URL, "/api/login", url.Values{"username": {"admin"}, "password": {"nope"}})
		res.Body.Close()
	}
	res = postForm(t, srv.URL, "/api/login", url.Values{"username": {"admin"}, "password": {"nope"}})
	defer res.Body.Close()
	if res.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("status = %d, want 429", res.StatusCode)
	}
	if res.Header.Get("Retry-After") != "300" {
		t.Errorf("Retry-After = %q, want 300", res.Header.Get("Retry-After"))
	}
}

// TestAuthSessionVerifyRevoke covers sessions semantics directly: expiry,
// idle timeout, revocation.
func TestAuthSessionVerifyRevoke(t *testing.T) {
	conn, _ := newTestDB(t)
	svc := auth.NewService(conn, t.TempDir())

	token, err := svc.CreateSession("admin", "owner", "", "", 604800)
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	id, ok := svc.VerifySession(token)
	if !ok || id.Username != "admin" || id.Type != "owner" {
		t.Fatalf("VerifySession = %v %v", id, ok)
	}
	if !svc.RevokeToken(token) {
		t.Fatalf("RevokeToken = false, want true")
	}
	if _, ok := svc.VerifySession(token); ok {
		t.Errorf("revoked session still valid")
	}
	if svc.RevokeToken(token) {
		t.Errorf("second revoke = true, want false")
	}

	// Expired row (absolute cap) is rejected and deleted eagerly.
	expired, _ := svc.CreateSession("admin", "owner", "", "", -10)
	if _, ok := svc.VerifySession(expired); ok {
		t.Errorf("expired session accepted")
	}
	var n int
	if err := conn.QueryRow(`SELECT COUNT(*) FROM sessions`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 0 {
		t.Errorf("sessions left = %d, want 0 (eager purge)", n)
	}

	// Idle timeout (default SESSION_IDLE_SECONDS = 1800).
	idle, _ := svc.CreateSession("admin", "owner", "", "", 604800)
	if _, err := conn.Exec(`UPDATE sessions SET last_seen_at=? WHERE token_hash=?`,
		float64(time.Now().Unix())-3600, hashToken(idle)); err != nil {
		t.Fatal(err)
	}
	if _, ok := svc.VerifySession(idle); ok {
		t.Errorf("idle session accepted")
	}
}

// TestAuthExpiredSessionShape: the retired JWT /refresh endpoint returns 401
// with the login-again detail (backend).
func TestAuthRefreshRetired(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)
	res, body := doJSON(t, http.MethodPost, srv.URL+"/api/refresh", "", nil)
	defer res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", res.StatusCode)
	}
	if body["detail"] != "Session expired — please log in again" {
		t.Errorf("detail = %v", body["detail"])
	}
}

// TestAuthLogoutRevokes mirrors /logout: row delete + cookie clear.
func TestAuthLogoutRevokes(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	srv := newServer(t, conn, dir)
	got := login(t, srv.URL, "admin", knownPassword)
	token := got["access_token"].(string)

	res, _ := doJSON(t, http.MethodPost, srv.URL+"/api/logout", token, nil)
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		t.Fatalf("logout status = %d, want 200", res.StatusCode)
	}
	if _, ok := auth.NewService(conn, dir).VerifySession(token); ok {
		t.Errorf("session survived logout")
	}
}

// TestAuthRequireOwner403 mirrors authz.require_owner.
func TestAuthRequireOwner403(t *testing.T) {
	conn, dir := newTestDB(t)
	seedOwner(t, conn, "admin", bcryptHash)
	svc := auth.NewService(conn, dir)
	inner := http.NewServeMux()
	svc.Mount(inner)
	guard := svc.RequireUser(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	guardedOwner := svc.RequireOwner(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	srv := newServerWith(t, inner, guard, guardedOwner)

	// No credentials → 401 with the FastAPI detail shape.
	res, body := doJSON(t, http.MethodGet, srv+"/api/_guard", "", nil)
	res.Body.Close()
	if res.StatusCode != http.StatusUnauthorized || body["detail"] != "Could not validate credentials" {
		t.Fatalf("401 shape = %d %v", res.StatusCode, body)
	}
	// A session whose role no longer matches the DB is rejected.
	token, _ := svc.CreateSession("admin", "admin", "", "", 604800)
	if _, err := conn.Exec(`UPDATE admins SET is_owner=0 WHERE username='admin'`); err != nil {
		t.Fatal(err)
	}
	res, _ = doJSON(t, http.MethodGet, srv+"/api/_owner", token, nil)
	res.Body.Close()
	if res.StatusCode != http.StatusForbidden {
		t.Fatalf("stale admin role = %d, want 403", res.StatusCode)
	}
}

// TestOwnerClaimFlow mirrors backend/routers/owner_claim: the key file is
// consumed by a successful claim and the response is a login-shaped session.
func TestOwnerClaimFlow(t *testing.T) {
	conn, dir := newTestDB(t)
	keyPath := filepath.Join(dir, "owner-claim.key")
	if err := os.WriteFile(keyPath, []byte("claim-key-abc\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	srv := newServer(t, conn, dir)

	res, body := doJSON(t, http.MethodGet, srv.URL+"/api/owner-claim", "", nil)
	res.Body.Close()
	if res.StatusCode != 200 || body["claimable"] != true {
		t.Fatalf("claim status = %d %v", res.StatusCode, body)
	}

	// Wrong key → 401, key file untouched.
	res, body = doJSON(t, http.MethodPost, srv.URL+"/api/owner-claim", "",
		map[string]any{"claim_key": "nope", "password": "supersecret1"})
	res.Body.Close()
	if res.StatusCode != 401 || body["detail"] != "That claim key is not valid" {
		t.Fatalf("bad key = %d %v", res.StatusCode, body)
	}
	if _, err := os.Stat(keyPath); err != nil {
		t.Fatalf("key consumed by a failed claim: %v", err)
	}

	// verify accepts without spending.
	res, body = doJSON(t, http.MethodPost, srv.URL+"/api/owner-claim/verify", "",
		map[string]any{"claim_key": "claim-key-abc"})
	res.Body.Close()
	if body["valid"] != true {
		t.Fatalf("verify = %v", body)
	}

	// Correct key → session, role owner, key consumed, owner row written.
	res, body = doJSON(t, http.MethodPost, srv.URL+"/api/owner-claim", "",
		map[string]any{"claim_key": "claim-key-abc", "password": "supersecret1", "username": "root"})
	res.Body.Close()
	if res.StatusCode != 200 || body["role"] != "owner" || body["username"] != "root" {
		t.Fatalf("claim = %d %v", res.StatusCode, body)
	}
	if _, err := os.Stat(keyPath); !os.IsNotExist(err) {
		t.Errorf("key file survived a successful claim")
	}
	var pw string
	var isOwner bool
	if err := conn.QueryRow(`SELECT password, is_owner FROM admins WHERE username='root'`).Scan(&pw, &isOwner); err != nil {
		t.Fatalf("owner row: %v", err)
	}
	if !isOwner || !auth.VerifyPassword("supersecret1", pw) {
		t.Errorf("owner row not written correctly")
	}
}

// TestOwnerClaimNoKey mirrors the 400 when no key file exists.
func TestOwnerClaimNoKey(t *testing.T) {
	conn, dir := newTestDB(t)
	srv := newServer(t, conn, dir)
	res, body := doJSON(t, http.MethodPost, srv.URL+"/api/owner-claim", "",
		map[string]any{"claim_key": "x", "password": "supersecret1"})
	res.Body.Close()
	if res.StatusCode != 400 || body["detail"] != "No claim key on this host. Run: ovm auth key" {
		t.Fatalf("no key = %d %v", res.StatusCode, body)
	}
}

func hashToken(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

func newServerWith(t *testing.T, inner *http.ServeMux, guard, owner http.HandlerFunc) string {
	t.Helper()
	inner.HandleFunc("/_guard", guard)
	inner.HandleFunc("/_owner", owner)
	root := http.NewServeMux()
	root.Handle("/api/", http.StripPrefix("/api", inner))
	srv := newHTTPServer(t, root)
	return srv
}
