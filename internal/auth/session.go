package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// TokenBytes = 256 bits of entropy; only the SHA-256 digest is stored
// (auth/sessions).
const TokenBytes = 32

// touchThrottleSeconds throttles the sliding last_seen write.
const touchThrottleSeconds = 300

// Identity is the frontend-shaped identity dict returned by the backend layer.
type Identity struct {
	Username string
	Type     string
}

// Service holds the shared DB handle plus in-memory rate-limit state.
//
// The DB pointer sits behind dbmu: a restore swaps the live database in place
// (panel.activateDatabase), and an unguarded field would race every query
// against the swap. Read it through DB(); NewService/DBSwap are the only
// writers.
type Service struct {
	dbmu sync.RWMutex
	db   *sql.DB

	DataDir      string
	TrustedProxy bool

	MaxSeconds  int
	IdleSeconds int

	mu       sync.Mutex
	attempts map[string][]float64 // login buckets
	failures map[string][]float64 // claim buckets
	idMu     sync.Mutex
	idCache  map[string]cachedIdentity
}

func NewService(db *sql.DB, dataDir string) *Service {
	s := &Service{
		db:           db,
		DataDir:      dataDir,
		TrustedProxy: strings.EqualFold(os.Getenv("TRUSTED_PROXY"), "true"),
		MaxSeconds:   envInt("SESSION_MAX_SECONDS", 604800),
		IdleSeconds:  envInt("SESSION_IDLE_SECONDS", 1800),
		attempts:     map[string][]float64{},
		failures:     map[string][]float64{},
		idCache:      map[string]cachedIdentity{},
	}
	go func() {
		t := time.NewTicker(time.Duration(cleanupInterval) * time.Second)
		defer t.Stop()
		for range t.C {
			s.pruneAttempts()
		}
	}()
	go func() {
		t := time.NewTicker(time.Hour)
		defer t.Stop()
		for range t.C {
			s.PurgeExpired()
		}
	}()
	return s
}

// DB returns the live database handle (swap-safe).
func (s *Service) DB() *sql.DB {
	s.dbmu.RLock()
	defer s.dbmu.RUnlock()
	return s.db
}

// DBSwap atomically replaces the live database handle and returns the
// previous one (activateDatabase closes it after the swap settles).
func (s *Service) DBSwap(fresh *sql.DB) *sql.DB {
	s.dbmu.Lock()
	defer s.dbmu.Unlock()
	old := s.db
	s.db = fresh
	return old
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
	raw, err := newToken()
	if err != nil {
		return "", err
	}
	now := nowSecs()
	if len(userAgent) > 256 {
		userAgent = userAgent[:256]
	}
	if len(ip) > 64 {
		ip = ip[:64]
	}
	if _, err := s.DB().Exec(
		`INSERT INTO Session (token_hash, username, role, created_at, expires_at, last_seen_at, user_agent, ip)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		tokenHash(raw), username, role, now, now+float64(ttl), now, nullIfEmpty(userAgent), nullIfEmpty(ip),
	); err != nil {
		return "", err
	}
	return raw, nil
}

// newToken mirrors secrets.token_urlsafe(32): 32 random bytes, unpadded
// URL-safe base64 (43 chars).
func newToken() (string, error) {
	buf := make([]byte, TokenBytes)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(buf), nil
}

// VerifySession resolves a raw token to its identity, or false when
// invalid/expired. Expired rows are deleted eagerly (sessions). The admin
// check is a JOIN in the same query: only sessions whose user is still an
// owner authenticate.
func (s *Service) VerifySession(raw string) (Identity, bool) {
	var zero Identity
	if raw == "" {
		return zero, false
	}
	th := tokenHash(raw)
	if ident, ok := s.cacheGet(th); ok {
		return ident, true
	}
	var id int64
	var ident Identity
	var expiresAt, lastSeen float64
	err := s.DB().QueryRow(
		`SELECT s.id, s.username, s.role, s.expires_at, s.last_seen_at
		 FROM Session s JOIN Admin a ON a.username = s.username AND a.is_owner = 1
		 WHERE s.token_hash = ?`,
		th,
	).Scan(&id, &ident.Username, &ident.Type, &expiresAt, &lastSeen)
	if err == sql.ErrNoRows {
		return zero, false
	}
	if err != nil {
		return zero, false
	}
	now := nowSecs()
	if now >= expiresAt || now-lastSeen > float64(s.IdleSeconds) {
		_, _ = s.DB().Exec(`DELETE FROM Session WHERE id = ?`, id)
		return zero, false
	}
	if now-lastSeen >= touchThrottleSeconds {
		_, _ = s.DB().Exec(`UPDATE Session SET last_seen_at = ? WHERE id = ?`, now, id)
	}
	s.cachePut(th, ident)
	return ident, true
}

const identityCacheTTLSeconds = 30
const identityCacheMaxEntries = 1024

type cachedIdentity struct {
	ident  Identity
	expiry float64
}

type ctxKey int

const identityCtxKey ctxKey = 0

func (s *Service) cacheGet(th string) (Identity, bool) {
	s.idMu.Lock()
	defer s.idMu.Unlock()
	e, ok := s.idCache[th]
	if !ok || nowSecs() >= e.expiry {
		if ok {
			delete(s.idCache, th)
		}
		return Identity{}, false
	}
	return e.ident, true
}

func (s *Service) cachePut(th string, ident Identity) {
	s.idMu.Lock()
	defer s.idMu.Unlock()
	if len(s.idCache) >= identityCacheMaxEntries {
		for k := range s.idCache {
			delete(s.idCache, k)
			break
		}
	}
	s.idCache[th] = cachedIdentity{ident: ident, expiry: nowSecs() + identityCacheTTLSeconds}
}

func (s *Service) cacheDelete(th string) {
	s.idMu.Lock()
	defer s.idMu.Unlock()
	delete(s.idCache, th)
}

func (s *Service) cacheDeleteUser(username string) {
	s.idMu.Lock()
	defer s.idMu.Unlock()
	for th, e := range s.idCache {
		if e.ident.Username == username {
			delete(s.idCache, th)
		}
	}
}

func (s *Service) RevokeToken(raw string) bool {
	if raw == "" {
		return false
	}
	th := tokenHash(raw)
	res, err := s.DB().Exec(`DELETE FROM Session WHERE token_hash = ?`, th)
	s.cacheDelete(th)
	if err != nil {
		return false
	}
	n, _ := res.RowsAffected()
	return n > 0
}

func (s *Service) RevokeUserSessions(username string) int {
	res, err := s.DB().Exec(`DELETE FROM Session WHERE username = ?`, username)
	s.cacheDeleteUser(username)
	if err != nil {
		return 0
	}
	n, _ := res.RowsAffected()
	return int(n)
}

// PurgeExpired deletes dead sessions (absolute cap OR idle timeout) and
// prunes the in-memory login buckets. Returns the total number of rows
// removed; the login_attempts table is left alone (see handler.go) and can
// be dropped in a later migration.
func (s *Service) PurgeExpired() int {
	total := 0
	now := nowSecs()
	if res, err := s.DB().Exec(
		`DELETE FROM Session WHERE expires_at <= ? OR (? - last_seen_at) > ?`,
		now, now, s.IdleSeconds,
	); err == nil {
		if n, _ := res.RowsAffected(); n > 0 {
			total += int(n)
		}
	}
	s.pruneAttempts()
	return total
}

// Authenticate checks the single owner credential row. Only the is_owner row
// authenticates; a leftover second-admin row never does (auth).
func (s *Service) Authenticate(username, password string) (Identity, bool) {
	var hash string
	var isOwner int64
	err := s.DB().QueryRow(`SELECT password, is_owner FROM Admin WHERE username = ?`, username).Scan(&hash, &isOwner)
	if err != nil || hash == "" || isOwner == 0 {
		_, _ = dummyVerify(password)
		return Identity{}, false
	}
	if !VerifyPassword(password, hash) {
		return Identity{}, false
	}
	if NeedsRehash(hash) {
		if fresh, err := HashPassword(password); err == nil {
			_, _ = s.DB().Exec(`UPDATE Admin SET password = ? WHERE username = ?`, fresh, username)
		}
	}
	return Identity{Username: username, Type: "owner"}, true
}

// bcryptWaste spends the same bcrypt time a real credential would so a
// missing/foreign row is not distinguishable by timing (auth _waste_verify).
func dummyVerify(password string) (bool, error) {
	return VerifyPassword(password, dummyBcryptHash), nil
}

// dummyBcryptHash is a valid $2b$12$ hash of an unknown random string; timing
// noise only, never a credential.
const dummyBcryptHash = "$2b$12$8SlU4k4IX4m.tP5fJQuWdenXCdwIlWYz8gF4lpOuVorq83CxScpTm"

func nullIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
