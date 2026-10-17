package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"os"
	"strconv"
	"sync"
	"time"
)

// TokenBytes = 256 bits of entropy; only the SHA-256 digest is stored
// (backend/auth/sessions.py).
const TokenBytes = 32

// touchThrottleSeconds throttles the sliding last_seen write.
const touchThrottleSeconds = 300

// Identity is the frontend-shaped identity dict returned by the Python layer.
type Identity struct {
	Username string
	Type     string
}

// Service holds the shared DB handle plus in-memory rate-limit state.
type Service struct {
	DB          *sql.DB
	DataDir     string
	TrustedProxy bool

	MaxSeconds  int
	IdleSeconds int

	mu       sync.Mutex
	attempts map[string][]float64 // login buckets (auth.py)
	failures map[string][]float64 // claim buckets (owner_claim.py)
}

// NewService builds the auth service with the panel defaults
// (SESSION_MAX_SECONDS=604800, SESSION_IDLE_SECONDS=1800).
func NewService(db *sql.DB, dataDir string) *Service {
	return &Service{
		DB:          db,
		DataDir:     dataDir,
		MaxSeconds:  envInt("SESSION_MAX_SECONDS", 604800),
		IdleSeconds: envInt("SESSION_IDLE_SECONDS", 1800),
		attempts:    map[string][]float64{},
		failures:    map[string][]float64{},
	}
}

func envInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func nowSecs() float64 { return float64(time.Now().UnixNano()) / 1e9 }

// tokenHash is the stored digest of a raw token.
func tokenHash(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

// CreateSession issues a session and returns the RAW token. ttl of 0 uses the
// service default.
func (s *Service) CreateSession(username, role, userAgent, ip string, ttl int) (string, error) {
	if ttl == 0 {
		ttl = s.MaxSeconds
	}
	raw := newToken()
	now := nowSecs()
	if len(userAgent) > 256 {
		userAgent = userAgent[:256]
	}
	if len(ip) > 64 {
		ip = ip[:64]
	}
	_, err := s.DB.Exec(
		`INSERT INTO sessions (token_hash, username, role, created_at, expires_at, last_seen_at, user_agent, ip)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		tokenHash(raw), username, role, now, now+float64(ttl), now, nullIfEmpty(userAgent), nullIfEmpty(ip),
	)
	if err != nil {
		return "", err
	}
	return raw, nil
}

// newToken mirrors secrets.token_urlsafe(32): 32 random bytes, unpadded
// URL-safe base64 (43 chars).
func newToken() string {
	buf := make([]byte, TokenBytes)
	if _, err := rand.Read(buf); err != nil {
		panic("crypto/rand: " + err.Error())
	}
	return base64.RawURLEncoding.EncodeToString(buf)
}

// VerifySession resolves a raw token to its identity, or false when
// invalid/expired. Expired rows are deleted eagerly (sessions.py).
func (s *Service) VerifySession(raw string) (Identity, bool) {
	var zero Identity
	if raw == "" {
		return zero, false
	}
	var id int64
	var ident Identity
	var expiresAt, lastSeen float64
	err := s.DB.QueryRow(
		`SELECT id, username, role, expires_at, last_seen_at FROM sessions WHERE token_hash = ?`,
		tokenHash(raw),
	).Scan(&id, &ident.Username, &ident.Type, &expiresAt, &lastSeen)
	if err == sql.ErrNoRows {
		return zero, false
	}
	if err != nil {
		return zero, false
	}
	now := nowSecs()
	if now >= expiresAt || now-lastSeen > float64(s.IdleSeconds) {
		_, _ = s.DB.Exec(`DELETE FROM sessions WHERE id = ?`, id)
		return zero, false
	}
	if now-lastSeen >= touchThrottleSeconds {
		// A failed touch must never break the request.
		_, _ = s.DB.Exec(`UPDATE sessions SET last_seen_at = ? WHERE id = ?`, now, id)
	}
	return ident, true
}

// RevokeToken deletes the session backing this raw token (logout).
func (s *Service) RevokeToken(raw string) bool {
	if raw == "" {
		return false
	}
	res, err := s.DB.Exec(`DELETE FROM sessions WHERE token_hash = ?`, tokenHash(raw))
	if err != nil {
		return false
	}
	n, _ := res.RowsAffected()
	return n > 0
}

// RevokeUserSessions deletes every session of a user.
func (s *Service) RevokeUserSessions(username string) int {
	res, err := s.DB.Exec(`DELETE FROM sessions WHERE username = ?`, username)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

// PurgeExpired deletes dead sessions (absolute cap OR idle timeout).
func (s *Service) PurgeExpired() int {
	now := nowSecs()
	res, err := s.DB.Exec(
		`DELETE FROM sessions WHERE expires_at <= ? OR (? - last_seen_at) > ?`,
		now, now, s.IdleSeconds,
	)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

// roleIsCurrent re-checks the session role against the admins table
// (auth.py role_is_current).
func (s *Service) roleIsCurrent(username, role string) bool {
	var isOwner int64
	err := s.DB.QueryRow(`SELECT is_owner FROM admins WHERE username = ?`, username).Scan(&isOwner)
	if err == sql.ErrNoRows || err != nil {
		return false
	}
	if role == "owner" {
		return isOwner != 0
	}
	return role == "admin"
}

// Authenticate checks the single owner credential row. Only the is_owner row
// authenticates; a leftover second-admin row never does (auth.py).
func (s *Service) Authenticate(username, password string) (Identity, bool) {
	var hash string
	var isOwner int64
	err := s.DB.QueryRow(`SELECT password, is_owner FROM admins WHERE username = ?`, username).Scan(&hash, &isOwner)
	if err != nil || hash == "" || isOwner == 0 {
		_, _ = bcryptWaste(password)
		return Identity{}, false
	}
	if !VerifyPassword(password, hash) {
		return Identity{}, false
	}
	if NeedsRehash(hash) {
		if fresh, err := HashPassword(password); err == nil {
			_, _ = s.DB.Exec(`UPDATE admins SET password = ? WHERE username = ?`, fresh, username)
		}
	}
	return Identity{Username: username, Type: "owner"}, true
}

// bcryptWaste spends the same bcrypt time a real credential would so a
// missing/foreign row is not distinguishable by timing (auth.py _waste_verify).
func bcryptWaste(password string) (bool, error) {
	return VerifyPassword(password, pythonDummyHash), nil
}

// pythonDummyHash is a valid $2b$12$ hash of an unknown random string; timing
// noise only, never a credential.
const pythonDummyHash = "$2b$12$8SlU4k4IX4m.tP5fJQuWdenXCdwIlWYz8gF4lpOuVorq83CxScpTm"

func nullIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
