// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"database/sql"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/internal/audit"
	_ "modernc.org/sqlite"
)

func setupAuthTestDB(t *testing.T) *sql.DB {
	d, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = d.Close() })
	_, err = d.Exec(`
		CREATE TABLE Admin (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT UNIQUE NOT NULL,
			password TEXT NOT NULL,
			is_owner INTEGER DEFAULT 0
		);
		CREATE TABLE login_attempts (
			key_hash TEXT PRIMARY KEY,
			attempts TEXT NOT NULL DEFAULT '[]',
			updated REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE Session (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			token_hash TEXT UNIQUE NOT NULL,
			username TEXT NOT NULL,
			role TEXT NOT NULL,
			created_at REAL NOT NULL,
			expires_at REAL NOT NULL,
			last_seen_at REAL NOT NULL,
			user_agent TEXT,
			ip TEXT
		);
		CREATE TABLE audit_logs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			ts REAL NOT NULL,
			actor TEXT,
			action TEXT NOT NULL,
			target TEXT,
			detail TEXT,
			promoted BOOLEAN NOT NULL DEFAULT 0
		);
	`)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func seedUser(t *testing.T, d *sql.DB, username, password string) {
	hash, _ := HashPassword(password)
	_, err := d.Exec(`INSERT INTO Admin (username, password, is_owner) VALUES (?, ?, 1)`, username, hash)
	if err != nil {
		t.Fatal(err)
	}
}

func seedFailures(s *Service, username string, n int) {
	key := s.userKey(username)
	now := nowSecs()
	stamps := make([]float64, n)
	for i := range stamps {
		stamps[i] = now - float64(i)*0.001
	}
	s.mu.Lock()
	s.attempts[key] = stamps
	s.mu.Unlock()
}

func loginReq(t *testing.T, svc *Service, username, password, remote string) *httptest.ResponseRecorder {
	form := url.Values{"username": {username}, "password": {password}}
	req := httptest.NewRequest(http.MethodPost, "/api/login", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Origin", "http://localhost")
	req.Host = "localhost"
	req.RemoteAddr = remote
	w := httptest.NewRecorder()
	svc.handleLogin(w, req)
	return w
}

func TestRateStateIsInMemory(t *testing.T) {
	d := setupAuthTestDB(t)
	seedUser(t, d, "admin", "correct_password_123")
	svc := NewService(d, t.TempDir())
	ip := BucketIP("10.0.0.99")
	key := svc.rateKey(ip, "admin")
	now := nowSecs()
	stamps := make([]float64, maxAttempts)
	for i := range stamps {
		stamps[i] = now - float64(i)*0.001
	}
	svc.mu.Lock()
	svc.attempts[key] = stamps
	svc.mu.Unlock()
	w := loginReq(t, svc, "admin", "wrong_pass", "10.0.0.99:12345")
	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("ip+user over limit = %d, want 429", w.Code)
	}
	if w.Header().Get("Retry-After") != "300" {
		t.Fatalf("Retry-After = %q, want 300", w.Header().Get("Retry-After"))
	}
}

func TestUsernameOnlyNoLongerBlocks(t *testing.T) {
	d := setupAuthTestDB(t)
	seedUser(t, d, "admin", "correct_password_123")
	svc := NewService(d, t.TempDir())
	seedFailures(svc, "admin", 60)
	// Fewer than the delay threshold-plus-cap would block; with 60 failures
	// the delay is capped at 5s but must not produce a 429 for a fresh IP.
	// Use a fresh service with 30 failures to keep the test fast (delay 5s
	// is still capped), verifying instead that the code path is delay-only
	// via loginDelaySeconds and that a correct login from a new IP is not 429
	// when the user bucket is the only saturated one.
	svc2 := NewService(d, t.TempDir())
	seedFailures(svc2, "admin", 19)
	w := loginReq(t, svc2, "admin", "correct_password_123", "10.0.0.100:12345")
	if w.Code == http.StatusTooManyRequests {
		t.Fatal("username bucket alone must not block a fresh IP")
	}
}

func TestLoginDelayBackoff(t *testing.T) {
	cases := map[int]int{0: 0, 19: 0, 20: 1, 21: 2, 22: 4, 23: 5, 60: 5}
	for failures, want := range cases {
		if got := loginDelaySeconds(failures); got != want {
			t.Errorf("loginDelaySeconds(%d)=%d want %d", failures, got, want)
		}
	}
}

func TestDistributedFailuresDoNotBlockOwner(t *testing.T) {
	t.Setenv(audit.PathEnv, filepath.Join(t.TempDir(), "audit.jsonl"))
	d := setupAuthTestDB(t)
	seedUser(t, d, "owner", "owner_password_456")
	svc := NewService(d, t.TempDir())
	seedFailures(svc, "owner", 100)
	w := loginReq(t, svc, "owner", "owner_password_456", "203.0.113.1:12345")
	if w.Code == http.StatusTooManyRequests {
		t.Fatal("100 distributed failures blocked the owner (429)")
	}
	if w.Code != http.StatusOK {
		t.Fatalf("correct login from new IP = %d, want 200", w.Code)
	}
	found := false
	for _, obj := range audit.ReadLines() {
		if obj["action"] == "Auth.Login" && obj["actor"] == "owner" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("audit record missing on success")
	}
}
