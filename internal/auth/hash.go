// Package auth ports backend/auth/{hash,sessions,auth,authz}.py: bcrypt
// credential hashing, opaque DB-backed sessions, login/claim endpoints and the
// FastAPI authorization dependencies.
package auth

import (
	"strings"
	"unicode/utf8"

	"golang.org/x/crypto/bcrypt"
)

// BcryptCost matches passlib/bcrypt's default (backend/auth/hash.py).
const BcryptCost = 12

const maxBytes = 72

// prepare encodes a password for bcrypt, truncating on a UTF-8 boundary so a
// multibyte password is never split mid-sequence (backend/auth/hash.py).
func prepare(password string) []byte {
	raw := []byte(password)
	if len(raw) <= maxBytes {
		return raw
	}
	cut := raw[:maxBytes]
	for len(cut) > 0 {
		if r, size := utf8.DecodeLastRune(cut); r != utf8.RuneError || size > 1 {
			break
		}
		cut = cut[:len(cut)-1]
	}
	return []byte(string(cut))
}

// HashPassword returns a bcrypt hash (12 rounds, $2b$ prefix). New hashes stay
// byte-comparable with the Python backend's.
func HashPassword(password string) (string, error) {
	h, err := bcrypt.GenerateFromPassword(prepare(password), BcryptCost)
	if err != nil {
		return "", err
	}
	// x/crypto emits the $2a$ variant; rewrite to $2b$ so stored hashes are
	// byte-identical to the Python backend's (bcrypt honors both on compare).
	return "$2b$" + string(h)[4:], nil
}

// VerifyPassword checks a password against a stored hash. It never panics and
// returns false for a malformed or foreign hash.
func VerifyPassword(plain, hashed string) bool {
	if hashed == "" {
		return false
	}
	return bcrypt.CompareHashAndPassword([]byte(hashed), prepare(plain)) == nil
}

// NeedsRehash reports a stored hash weaker than the current policy: unknown
// prefix, unparsable cost, or fewer than 12 rounds (backend/auth/hash.py).
func NeedsRehash(hashed string) bool {
	if hashed == "" {
		return true
	}
	parts := strings.Split(hashed, "$")
	if len(parts) < 4 {
		return true
	}
	switch parts[1] {
	case "2b", "2a", "2y", "2x":
	default:
		return true
	}
	cost := 0
	for _, c := range parts[2] {
		if c < '0' || c > '9' {
			return true
		}
		cost = cost*10 + int(c-'0')
	}
	return cost < BcryptCost
}
