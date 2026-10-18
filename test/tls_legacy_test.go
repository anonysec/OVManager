// Parity tests for migrate_legacy_tls, ported from the last version
// (backend/routers/tls.py at 07204ee^): a pair left in DATA_DIR/tls is copied
// onto the declared paths, once, and never over a pair already declared.
package tests

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/panel"
)

// declaredPaths points SSL_KEYFILE/SSL_CERTFILE at a temp dir beside DATA_DIR
// and returns the two declared paths.
func declaredPaths(t *testing.T, dataDir string) (keyPath, certPath string) {
	t.Helper()
	keyPath = filepath.Join(dataDir, "declared", "privkey.pem")
	certPath = filepath.Join(dataDir, "declared", "fullchain.pem")
	t.Setenv("SSL_KEYFILE", keyPath)
	t.Setenv("SSL_CERTFILE", certPath)
	return keyPath, certPath
}

// writeLegacyPair puts a pre-declaration pair in DATA_DIR/tls and returns the
// directory and the two paths.
func writeLegacyPair(t *testing.T, dataDir, keyPEM, certPEM string) (dir, keyPath, certPath string) {
	t.Helper()
	dir = filepath.Join(dataDir, "tls")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("legacy dir: %v", err)
	}
	keyPath = filepath.Join(dir, "privkey.pem")
	certPath = filepath.Join(dir, "fullchain.pem")
	if err := os.WriteFile(keyPath, []byte(keyPEM), 0o600); err != nil {
		t.Fatalf("legacy key: %v", err)
	}
	if err := os.WriteFile(certPath, []byte(certPEM), 0o644); err != nil {
		t.Fatalf("legacy cert: %v", err)
	}
	return dir, keyPath, certPath
}

// TestMigrateLegacyTLSCopiesPairOntoDeclaredPaths is the documented case: the
// pair moves onto the declared paths, the legacy copy stays, the second call
// does nothing.
func TestMigrateLegacyTLSCopiesPairOntoDeclaredPaths(t *testing.T) {
	env := newPanelEnv(t)
	keyPath, certPath := declaredPaths(t, env.dataDir)
	keyPEM, certPEM := mintPair(t, "legacy.example.com")
	legacyDir, legacyKey, legacyCert := writeLegacyPair(t, env.dataDir, keyPEM, certPEM)

	got := panel.MigrateLegacyTLS(env.dataDir)
	if got["ok"] != true || got["migrated"] != true {
		t.Fatalf("migrate = %v, want ok+migrated", got)
	}
	if got["from"] != legacyCert || got["to"] != certPath {
		t.Fatalf("from/to = %v/%v, want %s/%s", got["from"], got["to"], legacyCert, certPath)
	}

	// Copies rather than moves, at the declared paths.
	for _, want := range []struct{ path, content string }{
		{keyPath, keyPEM}, {certPath, certPEM},
	} {
		raw, err := os.ReadFile(want.path)
		if err != nil || string(raw) != want.content {
			t.Fatalf("declared %s not written from the legacy pair (err=%v)", want.path, err)
		}
	}
	if info, err := os.Stat(keyPath); err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("declared key mode = %v (err=%v), want 0600", info, err)
	}
	if info, err := os.Stat(certPath); err != nil || info.Mode().Perm() != 0o644 {
		t.Fatalf("declared cert mode = %v (err=%v), want 0644", info, err)
	}
	if _, err := os.Stat(legacyKey); err != nil {
		t.Fatalf("the legacy copy was removed: %v", err)
	}
	meta, err := os.ReadFile(filepath.Join(legacyDir, "meta.json"))
	if err != nil || !strings.Contains(string(meta), `"mode": "migrated"`) {
		t.Fatalf("meta.json = %s (err=%v), want mode migrated", meta, err)
	}

	// Idempotent: nothing left to do, and nothing rewritten.
	again := panel.MigrateLegacyTLS(env.dataDir)
	if again["ok"] != true || again["migrated"] != false {
		t.Fatalf("second migrate = %v, want ok and not migrated", again)
	}
	if raw, _ := os.ReadFile(certPath); string(raw) != certPEM {
		t.Fatalf("the second migrate rewrote the declared certificate")
	}
}

// TestMigrateLegacyTLSNothingToDo covers the common case: no legacy pair.
func TestMigrateLegacyTLSNothingToDo(t *testing.T) {
	env := newPanelEnv(t)
	keyPath, certPath := declaredPaths(t, env.dataDir)

	got := panel.MigrateLegacyTLS(env.dataDir)
	if got["ok"] != true || got["migrated"] != false {
		t.Fatalf("migrate = %v, want ok and not migrated", got)
	}
	for _, path := range []string{keyPath, certPath} {
		if _, err := os.Stat(path); err == nil {
			t.Fatalf("migration created %s from nothing", path)
		}
	}
}

// TestMigrateLegacyTLSNeverOverwritesADeclaredPair: an operator who already put
// a certificate where .env says keeps it.
func TestMigrateLegacyTLSNeverOverwritesADeclaredPair(t *testing.T) {
	env := newPanelEnv(t)
	keyPath, certPath := declaredPaths(t, env.dataDir)
	declaredKey, declaredCert := mintPair(t, "declared.example.com")
	if err := os.MkdirAll(filepath.Dir(keyPath), 0o755); err != nil {
		t.Fatalf("declared dir: %v", err)
	}
	if err := os.WriteFile(keyPath, []byte(declaredKey), 0o600); err != nil {
		t.Fatalf("declared key: %v", err)
	}
	if err := os.WriteFile(certPath, []byte(declaredCert), 0o644); err != nil {
		t.Fatalf("declared cert: %v", err)
	}
	legacyKey, legacyCert := mintPair(t, "legacy.example.com")
	writeLegacyPair(t, env.dataDir, legacyKey, legacyCert)

	got := panel.MigrateLegacyTLS(env.dataDir)
	if got["ok"] != true || got["migrated"] != false {
		t.Fatalf("migrate = %v, want ok and not migrated", got)
	}
	if raw, _ := os.ReadFile(keyPath); string(raw) != declaredKey {
		t.Fatalf("the declared key was overwritten")
	}
	if raw, _ := os.ReadFile(certPath); string(raw) != declaredCert {
		t.Fatalf("the declared certificate was overwritten")
	}
}

// TestMigrateLegacyTLSSkipsWhenTheDeclaredPathIsTheLegacyPath: an install whose
// .env names DATA_DIR/tls is already where the pair lives.
func TestMigrateLegacyTLSSkipsWhenTheDeclaredPathIsTheLegacyPath(t *testing.T) {
	env := newPanelEnv(t)
	keyPEM, certPEM := mintPair(t, "legacy.example.com")
	legacyDir, legacyKey, legacyCert := writeLegacyPair(t, env.dataDir, keyPEM, certPEM)
	t.Setenv("SSL_KEYFILE", legacyKey)
	t.Setenv("SSL_CERTFILE", legacyCert)

	got := panel.MigrateLegacyTLS(env.dataDir)
	if got["ok"] != true || got["migrated"] != false {
		t.Fatalf("migrate = %v, want ok and not migrated", got)
	}
	if !strings.HasPrefix(legacyKey, legacyDir) {
		t.Fatalf("test setup: legacy key %s outside %s", legacyKey, legacyDir)
	}
	if raw, _ := os.ReadFile(legacyCert); string(raw) != certPEM {
		t.Fatalf("the pair was rewritten in place")
	}
}

// TestMigrateLegacyTLSReportsAnInvalidLegacyPair never raises: the failure is
// the wording, and the declared paths stay untouched.
func TestMigrateLegacyTLSReportsAnInvalidLegacyPair(t *testing.T) {
	env := newPanelEnv(t)
	keyPath, certPath := declaredPaths(t, env.dataDir)
	writeLegacyPair(t, env.dataDir, "not a key", "not a cert")

	got := panel.MigrateLegacyTLS(env.dataDir)
	if got["ok"] != false {
		t.Fatalf("migrate = %v, want ok false", got)
	}
	msg, _ := got["error"].(string)
	if !strings.HasPrefix(msg, "Could not migrate the existing certificate: ") {
		t.Fatalf("error = %q, want the wording", msg)
	}
	for _, path := range []string{keyPath, certPath} {
		if _, err := os.Stat(path); err == nil {
			t.Fatalf("%s written despite the invalid pair", path)
		}
	}
}
