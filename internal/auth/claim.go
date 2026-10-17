package auth

import (
	"crypto/hmac"
	"database/sql"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// owner-claim constants (backend/routers/owner_claim.py).
const (
	claimKeyFile    = "owner-claim.key"
	maxClaimFail    = 5
	claimFailWindow = 300
)

type claimRequest struct {
	ClaimKey string `json:"claim_key"`
	Password string `json:"password"`
	Username string `json:"username"`
}

func (s *Service) claimKeyPath() string {
	dir := s.DataDir
	if dir == "" {
		dir = "data"
	}
	return filepath.Join(dir, claimKeyFile)
}

// readClaimKey returns the key on this host, or "" when there is none. An
// unreadable key file is an error, not a missing key.
func (s *Service) readClaimKey() (string, error) {
	path := s.claimKeyPath()
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if info.Size() > 4096 {
		return "", errKeyUnreadable{path + " is not a claim key file"}
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(raw)), nil
}

type errKeyUnreadable struct{ msg string }

func (e errKeyUnreadable) Error() string { return e.msg }

func (s *Service) ownerIsClaimed() bool {
	var hash sql.NullString
	err := s.DB.QueryRow(`SELECT password FROM admins WHERE is_owner = 1 LIMIT 1`).Scan(&hash)
	return err == nil && hash.Valid && hash.String != ""
}

func (s *Service) mountClaim(mux *http.ServeMux) {
	mux.HandleFunc("GET /owner-claim", s.handleClaimStatus)
	mux.HandleFunc("POST /owner-claim", s.handleClaimOwner)
	mux.HandleFunc("POST /owner-claim/verify", s.handleClaimVerify)
}

func (s *Service) handleClaimStatus(w http.ResponseWriter, r *http.Request) {
	claimed := s.ownerIsClaimed()
	keyPresent := false
	if !claimed {
		key, err := s.readClaimKey()
		if err != nil {
			keyPresent = true // unreadable file: don't disclose "no key"
		} else {
			keyPresent = key != ""
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"claimable": !claimed && keyPresent})
}

func (s *Service) handleClaimVerify(w http.ResponseWriter, r *http.Request) {
	var req claimRequest
	if !decodeJSON(w, r, &req) {
		return
	}
	if s.claimRateLimited(r) {
		return
	}
	key, err := s.readClaimKey()
	valid := err == nil && key != "" && hmac.Equal([]byte(key), []byte(strings.TrimSpace(req.ClaimKey)))
	if !valid {
		s.noteClaimFailure(r)
	}
	writeJSON(w, http.StatusOK, map[string]any{"valid": valid})
}

func (s *Service) handleClaimOwner(w http.ResponseWriter, r *http.Request) {
	var req claimRequest
	if !decodeJSON(w, r, &req) {
		return
	}
	if problem := passwordProblem(req.Password); problem != "" {
		writeValidation(w, "password", "Owner password "+problem)
		return
	}
	if s.claimRateLimited(r) {
		return
	}
	if s.ownerIsClaimed() {
		s.recoverOwner(w, r, req)
		return
	}

	key, err := s.readClaimKey()
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Cannot read the claim key file — re-run on the host: ovm auth key")
		return
	}
	if key == "" {
		writeDetail(w, http.StatusBadRequest, "No claim key on this host. Run: ovm auth key")
		return
	}
	if !hmac.Equal([]byte(key), []byte(strings.TrimSpace(req.ClaimKey))) {
		s.noteClaimFailure(r)
		writeDetail(w, http.StatusUnauthorized, "That claim key is not valid")
		return
	}

	chosen := strings.TrimSpace(req.Username)
	if chosen == "" {
		chosen = envOr("ADMIN_USERNAME", "admin")
	}
	var ownerID int64
	var ownerName string
	rowErr := s.DB.QueryRow(`SELECT id, username FROM admins WHERE is_owner = 1 LIMIT 1`).Scan(&ownerID, &ownerName)
	var conflictID int64
	conflictErr := s.DB.QueryRow(`SELECT id FROM admins WHERE username = ?`, chosen).Scan(&conflictID)

	if conflictErr == nil && (rowErr == sql.ErrNoRows || chosen != ownerName) {
		writeDetail(w, http.StatusConflict, "An admin with this username already exists")
		return
	}
	hash, err := HashPassword(req.Password)
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Could not create the owner account")
		return
	}
	if rowErr == sql.ErrNoRows {
		_, err = s.DB.Exec(`INSERT INTO admins (username, password, is_owner) VALUES (?, ?, 1)`, chosen, hash)
	} else {
		_, err = s.DB.Exec(`UPDATE admins SET username = ?, password = ?, is_owner = 1 WHERE id = ?`, chosen, hash, ownerID)
	}
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Could not create the owner account")
		return
	}
	_ = os.Remove(s.claimKeyPath())
	s.IssueSession(w, r, chosen, "owner")
}

// recoverOwner resets owner credentials with a fresh setup key (ovm auth
// reset); same key validation as a first claim.
func (s *Service) recoverOwner(w http.ResponseWriter, r *http.Request, req claimRequest) {
	key, err := s.readClaimKey()
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Cannot read the claim key file — re-run on the host: ovm auth key")
		return
	}
	if key == "" {
		writeDetail(w, http.StatusBadRequest, "No claim key on this host. Run: ovm auth reset")
		return
	}
	if !hmac.Equal([]byte(key), []byte(strings.TrimSpace(req.ClaimKey))) {
		s.noteClaimFailure(r)
		writeDetail(w, http.StatusUnauthorized, "That setup key is not valid")
		return
	}
	var ownerID int64
	var ownerName string
	if err := s.DB.QueryRow(`SELECT id, username FROM admins WHERE is_owner = 1 LIMIT 1`).Scan(&ownerID, &ownerName); err != nil {
		writeDetail(w, http.StatusConflict, "No owner row found. Sign in, or reinstall the panel.")
		return
	}
	chosen := strings.TrimSpace(req.Username)
	if chosen == "" {
		chosen = ownerName
	}
	var conflictID int64
	if err := s.DB.QueryRow(`SELECT id FROM admins WHERE username = ?`, chosen).Scan(&conflictID); err == nil && conflictID != ownerID {
		writeDetail(w, http.StatusConflict, "An admin with this username already exists")
		return
	}
	hash, err := HashPassword(req.Password)
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Could not reset the owner account")
		return
	}
	if _, err := s.DB.Exec(`UPDATE admins SET username = ?, password = ?, is_owner = 1 WHERE id = ?`, chosen, hash, ownerID); err != nil {
		writeDetail(w, http.StatusInternalServerError, "Could not reset the owner account")
		return
	}
	s.RevokeUserSessions(chosen)
	_ = os.Remove(s.claimKeyPath())
	s.IssueSession(w, r, chosen, "owner")
}

// claimRateLimited reproduces owner_claim.py's per-IP failure window.
func (s *Service) claimRateLimited(r *http.Request) bool {
	key := sha16(s.clientIP(r))
	s.mu.Lock()
	defer s.mu.Unlock()
	now := nowSecs()
	fresh := s.failures[key][:0]
	for _, t := range s.failures[key] {
		if now-t < claimFailWindow {
			fresh = append(fresh, t)
		}
	}
	if len(fresh) == 0 {
		delete(s.failures, key)
	} else {
		s.failures[key] = fresh
	}
	if len(s.failures) > 1000 {
		for k, times := range s.failures {
			if len(times) == 0 || now-times[len(times)-1] > claimFailWindow {
				delete(s.failures, k)
			}
		}
	}
	return len(fresh) >= maxClaimFail
}

func (s *Service) noteClaimFailure(r *http.Request) {
	key := sha16(s.clientIP(r))
	s.mu.Lock()
	defer s.mu.Unlock()
	s.failures[key] = append(s.failures[key], nowSecs())
}

// --- validation + JSON helpers shared with the owner claim ---

const passwordMinLength = 8

var passwordPlaceholders = []string{"change-me", "changeme", "change_me", "password123", "admin123"}

// passwordProblem mirrors backend/validation.py password_problem.
func passwordProblem(value string) string {
	if value == "" {
		return "must not be empty"
	}
	if strings.ContainsAny(value, "\n\r") {
		return "must be a single line"
	}
	if len([]rune(value)) < passwordMinLength {
		return "must be at least 8 characters (the panel requires >= 8)"
	}
	lowered := strings.ToLower(value)
	for _, p := range passwordPlaceholders {
		if strings.Contains(lowered, p) {
			return "looks like a placeholder — choose a strong password"
		}
	}
	return ""
}

// writeValidation emits FastAPI's 422 error-list shape.
func writeValidation(w http.ResponseWriter, field, msg string) {
	writeJSON(w, http.StatusUnprocessableEntity, map[string]any{
		"detail": []map[string]any{{
			"type": "value_error",
			"loc":  []any{"body", field},
			"msg":  "Value error, " + msg,
		}},
	})
}

func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) bool {
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]any{
			"detail": []map[string]any{{
				"type": "json_invalid",
				"loc":  []any{"body"},
				"msg":  "JSON decode error",
			}},
		})
		return false
	}
	return true
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
