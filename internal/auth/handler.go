package auth

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net"
	"net/http"
	"net/url"
	"strings"
)

// Response is the FastAPI ResponseModel envelope.
type Response struct {
	Success bool   `json:"success"`
	Msg     string `json:"msg"`
	Data    any    `json:"data"`
}

// Login rate limits (backend/auth/auth.py).
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
	if err := r.ParseForm(); err != nil {
		writeDetail(w, http.StatusBadRequest, "Invalid form data")
		return
	}
	username := r.PostFormValue("username")
	password := r.PostFormValue("password")
	ip := s.clientIP(r)

	s.purgeStaleAttempts()
	if s.bucketExceeded(s.rateKey(ip, username), maxAttempts) ||
		s.bucketExceeded(s.ipKey(ip), maxPerIP) ||
		s.bucketExceeded(s.userKey(username), maxPerUser) {
		w.Header().Set("Retry-After", "300")
		writeDetail(w, http.StatusTooManyRequests, "Too many login attempts. Please try again later.")
		return
	}

	ident, ok := s.Authenticate(username, password)
	if !ok {
		now := nowSecs()
		s.putBucket(s.rateKey(ip, username), append(s.bucket(s.rateKey(ip, username)), now))
		s.putBucket(s.ipKey(ip), append(s.bucket(s.ipKey(ip)), now))
		s.putBucket(s.userKey(username), append(s.bucket(s.userKey(username)), now))
		w.Header().Set("WWW-Authenticate", "Bearer")
		writeDetail(w, http.StatusUnauthorized, "The username or password is incorrect")
		return
	}
	s.clearBucket(s.rateKey(ip, username))
	s.clearBucket(s.userKey(username))
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
	secure := r.TLS != nil
	if s.TrustedProxy && firstProto(r.Header.Get("X-Forwarded-Proto")) == "https" {
		secure = true
	}
	http.SetCookie(w, &http.Cookie{
		Name:     "ovm_session",
		Value:    raw,
		Path:     "/",
		MaxAge:   s.MaxSeconds,
		HttpOnly: true,
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
	})
	writeJSON(w, http.StatusOK, map[string]any{
		"access_token":  raw,
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
	http.SetCookie(w, &http.Cookie{Name: "ovm_session", Value: "", Path: "/", MaxAge: -1})
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
	if ident.Type != "admin" && ident.Type != "owner" {
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
		// CSRF guard: a cross-origin mutating request must carry an Origin that
		// matches the panel host. Missing Origin is allowed (non-browser / test
		// clients and same-origin fetches that omit it); a mismatched Origin is
		// rejected. This blocks cross-site POST/PUT/DELETE without breaking the
		// existing test harness, which sends no Origin header.
		if isMutatingMethod(r.Method) {
			if o := r.Header.Get("Origin"); o != "" && !originAllowed(o, r) {
				writeDetail(w, http.StatusForbidden, "Origin not allowed")
				return
			}
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

func originAllowed(origin string, r *http.Request) bool {
	u, err := url.Parse(origin)
	if err != nil || u.Host == "" {
		return false
	}
	host := r.Host
	if host == "" {
		host = r.URL.Host
	}
	return strings.EqualFold(u.Host, host)
}

func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return h[len("Bearer "):]
	}
	return ""
}

// clientIP honours X-Forwarded-For only behind a trusted proxy.
//
// ponytail: rightmost XFF entry only; add X-Real-IP/Forwarded when a second
// proxy hop shows up in the field.
func (s *Service) clientIP(r *http.Request) string {
	if s.TrustedProxy {
		if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
			parts := strings.Split(xff, ",")
			if v := strings.TrimSpace(parts[len(parts)-1]); v != "" {
				return v
			}
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	return host
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

// --- in-memory rate-limit buckets (auth.py) ---

func (s *Service) bucket(key string) []float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := nowSecs()
	fresh := s.attempts[key][:0]
	for _, t := range s.attempts[key] {
		if now-t < lockoutSeconds {
			fresh = append(fresh, t)
		}
	}
	if len(fresh) == 0 {
		delete(s.attempts, key)
	} else {
		s.attempts[key] = fresh
	}
	return fresh
}

func (s *Service) putBucket(key string, times []float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.attempts[key] = times
	if overflow := len(s.attempts) - maxBuckets; overflow > 0 {
		for k := range s.attempts {
			delete(s.attempts, k)
			if overflow--; overflow == 0 {
				break
			}
		}
	}
}

func (s *Service) clearBucket(key string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.attempts, key)
}

func (s *Service) bucketExceeded(key string, limit int) bool {
	return len(s.bucket(key)) >= limit
}

func (s *Service) purgeStaleAttempts() {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := nowSecs()
	for k, times := range s.attempts {
		if len(times) == 0 || now-times[len(times)-1] > lockoutSeconds {
			delete(s.attempts, k)
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
