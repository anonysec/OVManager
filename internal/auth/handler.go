package auth

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/go/internal/audit"
)

// Response is the FastAPI ResponseModel envelope.
type Response struct {
	Success bool   `json:"success"`
	Msg     string `json:"msg"`
	Data    any    `json:"data"`
}

// Login rate limits (backend).
const (
	maxAttempts     = 5
	maxPerIP        = 20
	maxPerUser      = 60
	lockoutSeconds  = 300
	cleanupInterval = 600
	maxBuckets      = 10000
)

// Mount registers the auth routes the routers expose, relative to the
// caller's prefix (app.py includes them under /api).
func (s *Service) Mount(mux *http.ServeMux) {
	mux.HandleFunc("POST /login", s.handleLogin)
	mux.HandleFunc("POST /logout", s.handleLogout)
	mux.HandleFunc("POST /refresh", s.handleRefresh)
	s.mountClaim(mux)
}

// handleRefresh is the retired JWT endpoint: 401 drives the frontend's forced
// logout path.
func (s *Service) handleRefresh(w http.ResponseWriter, r *http.Request) {
	writeDetail(w, http.StatusUnauthorized, "Session expired — please log in again")
}

func (s *Service) handleLogin(w http.ResponseWriter, r *http.Request) {
	// The session is a cookie and this response sets it, so a cross-site POST
	// would leave the victim's browser holding the attacker's session — the
	// SPA acts on the cookie, so the victim would act as the attacker.
	// Rejected before the rate limiter sees it, so a cross-site caller cannot
	// spend the victim's login budget either.
	if s.originRejected(r) {
		writeDetail(w, http.StatusForbidden, "Origin not allowed")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 16*1024)
	if err := r.ParseForm(); err != nil {
		writeDetail(w, http.StatusBadRequest, "Invalid form data")
		return
	}
	username := r.PostFormValue("username")
	password := r.PostFormValue("password")
	ip := BucketIP(s.clientIP(r))

	// Check all three rate limit buckets atomically
	if s.checkBucket(s.rateKey(ip, username), maxAttempts) ||
		s.checkBucket(s.ipKey(ip), maxPerIP) ||
		s.checkBucket(s.userKey(username), maxPerUser) {
		w.Header().Set("Retry-After", "300")
		writeDetail(w, http.StatusTooManyRequests, "Too many login attempts. Please try again later.")
		return
	}

	ident, ok := s.Authenticate(username, password)
	if !ok {
		// Record the failed attempt in all three buckets
		s.incrementBucket(s.rateKey(ip, username))
		s.incrementBucket(s.ipKey(ip))
		s.incrementBucket(s.userKey(username))
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeDetail(w, http.StatusUnauthorized, "The username or password is incorrect")
		return
	}
	s.clearBucket(s.rateKey(ip, username))
	s.clearBucket(s.userKey(username))
	audit.Record(s.DB(), ident.Username, "auth.login", "info",
		"Signed in.", map[string]any{"target": ident.Username, "role": ident.Type})
	s.IssueSession(w, r, ident.Username, ident.Type)
}

// IssueSession opens a session and returns the login-shaped response: token +
// cookie. The owner claim returns the same shape.
func (s *Service) IssueSession(w http.ResponseWriter, r *http.Request, username, role string) {
	s.PurgeExpired()
	raw, err := s.CreateSession(username, role, r.UserAgent(), s.clientIP(r), 0)
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Could not create a session")
		return
	}
	http.SetCookie(w, &http.Cookie{
		Name:     "ovm_session",
		Value:    raw,
		Path:     "/",
		MaxAge:   s.MaxSeconds,
		HttpOnly: true,
		Secure:   true,
		SameSite: http.SameSiteLaxMode,
	})
	writeJSON(w, http.StatusOK, map[string]any{
		"refresh_token": nil,
		"token_type":    "bearer",
		"username":      username,
		"role":          role,
	})
}

func (s *Service) handleLogout(w http.ResponseWriter, r *http.Request) {
	raw := bearerToken(r)
	if raw == "" {
		if c, err := r.Cookie("ovm_session"); err == nil {
			raw = c.Value
		}
	}
	if raw != "" {
		s.RevokeToken(raw)
	}
	http.SetCookie(w, &http.Cookie{Name: "ovm_session", Value: "", Path: "/", MaxAge: -1, HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode})
	writeJSON(w, http.StatusOK, map[string]any{"detail": "Logged out"})
}

// CurrentUser resolves the presented credentials to an identity
// (auth.py get_current_user). It is also exposed for node-facing routers.
func (s *Service) CurrentUser(r *http.Request) (Identity, bool) {
	raw := bearerToken(r)
	if raw == "" {
		if c, err := r.Cookie("ovm_session"); err == nil {
			raw = c.Value
		}
	}
	if raw == "" {
		return Identity{}, false
	}
	ident, ok := s.VerifySession(raw)
	if !ok {
		return Identity{}, false
	}
	if ident.Type != "owner" {
		return Identity{}, false
	}
	if !s.roleIsCurrent(ident.Username, ident.Type) {
		return Identity{}, false
	}
	return ident, true
}

// RequireUser wraps a handler with the 401 gate.
func (s *Service) RequireUser(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if _, ok := s.CurrentUser(r); !ok {
			w.Header().Set("WWW-Authenticate", "Bearer")
			writeDetail(w, http.StatusUnauthorized, "Could not validate credentials")
			return
		}
		// CSRF guard: cookie-authenticated mutations must carry an Origin
		// matching scheme/host/port. Bearer API clients may omit Origin.
		if s.originRejected(r) {
			writeDetail(w, http.StatusForbidden, "Origin not allowed")
			return
		}
		next(w, r)
	}
}

// RequireOwner mirrors authz.require_owner.
func (s *Service) RequireOwner(next http.HandlerFunc) http.HandlerFunc {
	return s.RequireUser(func(w http.ResponseWriter, r *http.Request) {
		ident, _ := s.CurrentUser(r)
		if ident.Type != "owner" {
			writeDetail(w, http.StatusForbidden, "This action requires owner privileges")
			return
		}
		next(w, r)
	})
}

func isMutatingMethod(m string) bool {
	switch m {
	case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		return true
	}
	return false
}

// originRejected reports whether a mutating request carries a malformed or
// cross-origin Origin header. A missing Origin remains allowed for non-browser
// API clients; a supplied Origin must match the request's externally visible
// scheme, host and port.
func (s *Service) originRejected(r *http.Request) bool {
	if !isMutatingMethod(r.Method) {
		return false
	}
	hasBearer := strings.HasPrefix(strings.TrimSpace(r.Header.Get("Authorization")), "Bearer ")
	hasCookie := false
	if c, err := r.Cookie("ovm_session"); err == nil && c.Value != "" {
		hasCookie = true
	}
	hasValidBearer := false
	if hasBearer {
		raw := bearerToken(r)
		if _, ok := s.VerifySession(raw); ok {
			hasValidBearer = true
		}
	}
	origins := r.Header.Values("Origin")
	if len(origins) == 0 {
		// Cookie-authed browsers must send Origin on mutations; API clients
		// using a *verified* Bearer token remain allowed without it.
		return hasCookie && !hasValidBearer
	}
	if len(origins) != 1 {
		return true
	}
	return !s.originAllowed(origins[0], r)
}

func (s *Service) originAllowed(origin string, r *http.Request) bool {
	if strings.Contains(origin, "#") {
		return false
	}
	u, err := url.Parse(origin)
	if err != nil || u.Opaque != "" || u.User != nil || u.Host == "" ||
		u.Path != "" || u.RawPath != "" || u.RawQuery != "" || u.ForceQuery ||
		u.Fragment != "" || u.RawFragment != "" {
		return false
	}

	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" {
		return false
	}

	requestScheme := "http"
	if r.TLS != nil {
		requestScheme = "https"
	} else if s.TrustedProxy {
		forwardedScheme := strings.ToLower(firstProto(r.Header.Get("X-Forwarded-Proto")))
		if forwardedScheme != "" && forwardedScheme != "http" && forwardedScheme != "https" {
			return false
		}
		if forwardedScheme != "" {
			requestScheme = forwardedScheme
		}
	}
	if scheme != requestScheme {
		return false
	}

	host := r.Host
	if host == "" && r.URL != nil {
		host = r.URL.Host
	}
	originHost, originPort, ok := originHostPort(u.Host, scheme)
	if !ok {
		return false
	}
	requestHost, requestPort, ok := originHostPort(host, requestScheme)
	return ok && originHost == requestHost && originPort == requestPort
}

// originHostPort normalizes the host part of an HTTP origin, including the
// scheme's default port, so an explicit :443 and an omitted HTTPS port compare
// as the same origin. Malformed and out-of-range ports are rejected.
func originHostPort(host, scheme string) (string, string, bool) {
	u, err := url.Parse("//" + host)
	if err != nil || u.Host == "" || u.User != nil || u.Path != "" ||
		u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.RawFragment != "" {
		return "", "", false
	}
	hostname := strings.ToLower(u.Hostname())
	if hostname == "" || strings.HasSuffix(u.Host, ":") {
		return "", "", false
	}

	port := u.Port()
	if port == "" {
		switch scheme {
		case "http":
			port = "80"
		case "https":
			port = "443"
		default:
			return "", "", false
		}
	} else {
		parsedPort, err := strconv.Atoi(port)
		if err != nil || parsedPort < 1 || parsedPort > 65535 {
			return "", "", false
		}
		port = strconv.Itoa(parsedPort)
	}
	return hostname, port, true
}

func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return h[len("Bearer "):]
	}
	return ""
}

func (s *Service) clientIP(r *http.Request) string {
	return ClientIP(s.TrustedProxy, r)
}

func firstProto(v string) string {
	if i := strings.IndexByte(v, ','); i >= 0 {
		v = v[:i]
	}
	return strings.TrimSpace(v)
}

// Sha16 is the shared rate-limit bucket key: the first 16 hex characters of
// the SHA-256 of s. Exported so every package (auth, panel) hashes the same
// way instead of keeping private copies.
func Sha16(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])[:16]
}

func (s *Service) rateKey(ip, username string) string {
	return Sha16(ip + "\x00" + strings.ToLower(username))
}

func (s *Service) userKey(username string) string {
	return Sha16("user\x00" + strings.ToLower(username))
}

func (s *Service) ipKey(ip string) string { return Sha16(ip) }

// --- in-memory rate-limit buckets (auth) ---

func (s *Service) clearBucket(key string) {
	s.mu.Lock()
	delete(s.attempts, key)
	s.mu.Unlock()
	if db := s.DB(); db != nil {
		_, _ = db.Exec(`DELETE FROM login_attempts WHERE key_hash = ?`, key)
	}
}

// checkBucket reports whether a bucket is at or over its limit, without modifying it.
func (s *Service) checkBucket(key string, limit int) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := nowSecs()
	var times []float64

	if len(s.attempts[key]) == 0 && s.DB() != nil {
		var rawAttempts string
		if err := s.DB().QueryRow(`SELECT attempts FROM login_attempts WHERE key_hash = ?`, key).Scan(&rawAttempts); err == nil && rawAttempts != "" {
			_ = json.Unmarshal([]byte(rawAttempts), &times)
		}
	} else {
		times = s.attempts[key]
	}

	fresh := make([]float64, 0, len(times))
	for _, t := range times {
		if now-t < lockoutSeconds {
			fresh = append(fresh, t)
		}
	}
	if len(fresh) == 0 {
		delete(s.attempts, key)
	} else {
		s.attempts[key] = fresh
	}
	return len(fresh) >= limit
}

// incrementBucket adds the current timestamp to a bucket (used on failed login).
func (s *Service) incrementBucket(key string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := nowSecs()
	times := s.attempts[key]
	if len(times) == 0 && s.DB() != nil {
		var rawAttempts string
		if err := s.DB().QueryRow(`SELECT attempts FROM login_attempts WHERE key_hash = ?`, key).Scan(&rawAttempts); err == nil && rawAttempts != "" {
			_ = json.Unmarshal([]byte(rawAttempts), &times)
		}
	}

	fresh := make([]float64, 0, len(times)+1)
	for _, t := range times {
		if now-t < lockoutSeconds {
			fresh = append(fresh, t)
		}
	}
	fresh = append(fresh, now)
	s.attempts[key] = fresh
	if overflow := len(s.attempts) - maxBuckets; overflow > 0 {
		type victim struct {
			k    string
			last float64
		}
		var victims []victim
		for k, ts := range s.attempts {
			last := 0.0
			if len(ts) > 0 {
				last = ts[len(ts)-1]
			}
			victims = append(victims, victim{k, last})
		}
		sort.Slice(victims, func(i, j int) bool { return victims[i].last < victims[j].last })
		for i := 0; i < overflow && i < len(victims); i++ {
			delete(s.attempts, victims[i].k)
		}
	}

	if db := s.DB(); db != nil {
		if payload, err := json.Marshal(fresh); err == nil {
			_, _ = db.Exec(`INSERT INTO login_attempts (key_hash, attempts, updated)
				VALUES (?, ?, ?)
				ON CONFLICT(key_hash) DO UPDATE SET attempts = excluded.attempts, updated = excluded.updated`,
				key, string(payload), now)
		}
	}
}

// --- shared HTTP helpers ---

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeDetail(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

// WriteJSON / WriteDetail / WriteValidation are the exported twins the users
// package needs to keep FastAPI's response shapes.
func WriteJSON(w http.ResponseWriter, status int, body any) { writeJSON(w, status, body) }

// WriteDetail writes the {"detail": ...} FastAPI error body.
func WriteDetail(w http.ResponseWriter, status int, detail string) { writeDetail(w, status, detail) }

// WriteValidation writes FastAPI's 422 error-list body.
func WriteValidation(w http.ResponseWriter, field, msg string) { writeValidation(w, field, msg) }
