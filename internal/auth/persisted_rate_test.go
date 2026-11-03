// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package auth

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	_ "modernc.org/sqlite"
)

func setupAuthTestDB(t *testing.T) *sql.DB {
	d, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = d.Close() })
	_, err = d.Exec(`
		CREATE TABLE admins (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT UNIQUE NOT NULL,
			password_hash TEXT NOT NULL,
			is_owner INTEGER DEFAULT 0
		);
		CREATE TABLE login_attempts (
			key_hash TEXT PRIMARY KEY,
			attempts TEXT NOT NULL DEFAULT '[]',
			updated REAL NOT NULL DEFAULT 0
		);
		CREATE TABLE audit_logs (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
			user TEXT,
			action TEXT,
			level TEXT,
			message TEXT,
			metadata TEXT
		);
	`)
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestPersistedRateLimitSurvivesRestart(t *testing.T) {
	d := setupAuthTestDB(t)

	// Create owner user
	hash, _ := HashPassword("correct_password_123")
	_, err := d.Exec(`INSERT INTO admins (username, password_hash, is_owner) VALUES ('admin', ?, 1)`, hash)
	if err != nil {
		t.Fatal(err)
	}

	dataDir := t.TempDir()

	// Seed the persisted per-user bucket directly with maxPerUser recent
	// attempts, avoiding 60 live bcrypt logins (which exceed the 300s window
	// under the race detector). This preserves the persistence assertion.
	now := nowSecs()
	stamps := make([]float64, maxPerUser)
	for i := range stamps {
		stamps[i] = now - float64(i)*0.001
	}
	payload, _ := json.Marshal(stamps)
	userKey := Sha16("user\x00admin")
	if _, err := d.Exec(`INSERT INTO login_attempts (key_hash, attempts, updated) VALUES (?, ?, ?)`,
		userKey, string(payload), now); err != nil {
		t.Fatal(err)
	}

	svc1 := NewService(d, dataDir)

	// Any further attempt for the same user must be 429.
	form := url.Values{"username": {"admin"}, "password": {"wrong_pass"}}
	req := httptest.NewRequest(http.MethodPost, "/api/login", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Origin", "http://localhost")
	req.Host = "localhost"
	req.RemoteAddr = "10.0.0.99:12345"
	w := httptest.NewRecorder()
	svc1.handleLogin(w, req)
	if w.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429 Too Many Requests after exceeding maxPerUser, got %d", w.Code)
	}

	// SIMULATE PROCESS RESTART: Create a brand new Service instance with empty memory
	svc2 := NewService(d, dataDir)

	// The per-user lockout MUST persist across restarts!
	reqAfterRestart := httptest.NewRequest(http.MethodPost, "/api/login", strings.NewReader(form.Encode()))
	reqAfterRestart.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	reqAfterRestart.Header.Set("Origin", "http://localhost")
	reqAfterRestart.Host = "localhost"
	reqAfterRestart.RemoteAddr = "10.0.0.100:12345" // new IP
	wAfter := httptest.NewRecorder()
	svc2.handleLogin(wAfter, reqAfterRestart)

	if wAfter.Code != http.StatusTooManyRequests {
		t.Fatalf("SECURITY FLAW: Rate limit did not survive restart! Got %d, want 429", wAfter.Code)
	}
}
