// migrate_legacy_tls (backend/routers/tls.py at 07204ee^), ported whole.
//
// Where the certificate lives used to be two answers with a hidden winner: the
// path named in .env, and DATA_DIR/tls. The declared path wins now, so an
// install that keeps its pair in DATA_DIR/tls would silently fall back to plain
// HTTP — the one outcome that is both silent and total. This copies that pair
// onto the declared paths, before the first read of the certificate.
package panel

import (
	"os"
	"path/filepath"
)

// legacyPair is legacy_pair: the pre-declaration location, when it holds a pair.
func legacyPair(dataDirPath string) (keyPath, certPath string, ok bool) {
	dir := filepath.Join(dataDirPath, "tls")
	keyPath = filepath.Join(dir, "privkey.pem")
	certPath = filepath.Join(dir, "fullchain.pem")
	if fileExists(keyPath) && fileExists(certPath) {
		return keyPath, certPath, true
	}
	return "", "", false
}

// MigrateLegacyTLS copies a pre-declaration pair onto the declared paths. Never
// raises: every failure is reported in the returned envelope.
//
// Copies rather than moves, and only when the declared path holds nothing —
// an operator who has already put a certificate where .env says does not get it
// overwritten by one from the old directory.
func MigrateLegacyTLS(dataDirPath string) map[string]any {
	oldKey, oldCert, ok := legacyPair(dataDirPath)
	if !ok {
		return map[string]any{"ok": true, "migrated": false}
	}
	newKey, newCert := sslKeyPath(), sslCertPath()
	if resolvePath(newKey) == resolvePath(oldKey) {
		return map[string]any{"ok": true, "migrated": false}
	}
	if fileExists(newKey) && fileExists(newCert) {
		return map[string]any{"ok": true, "migrated": false}
	}

	keyBytes, keyErr := os.ReadFile(oldKey)
	certBytes, certErr := os.ReadFile(oldCert)
	err := keyErr
	if err == nil {
		err = certErr
	}
	if err == nil {
		// The write path is the panel's own transaction (validate, atomic
		// replace, retain the previous pair) now lives as a package-level
		// function, so this calls it directly — one implementation, not two.
		// ponytail: the write mutex is package-global, so during the migration
		// window a *live* handler's write serializes against it through the
		// same lock. Migration runs before the panel serves, so this is fine.
		_, err = writeManagedFiles(keyBytes, certBytes, "migrated")
	}
	if err != nil {
		return map[string]any{"ok": false,
			"error": "Could not migrate the existing certificate: " + err.Error()}
	}
	return map[string]any{"ok": true, "migrated": true, "from": oldCert, "to": newCert}
}
