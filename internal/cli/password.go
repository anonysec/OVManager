// `ovm reset-password` (cli/password.py): rewrite the owner credential in the
// database. Never echoes the value.
package cli

import (
	"os"
	"path/filepath"
	"strings"

	"ovmanager-go/internal/auth"
	"ovmanager-go/internal/db"
)

func runResetPassword(install Install, dataDir, password string) (string, int) {
	if password == "" {
		password = os.Getenv("OVM_ADMIN_PASS")
	}
	if password == "" {
		return block([]string{failedLine("No password given (set OVM_ADMIN_PASS or pass --admin-pass)")}), 1
	}
	if reason := auth.PasswordProblem(password); reason != "" {
		return block([]string{failedLine("Admin password " + reason)}), 1
	}
	if info, err := os.Stat(install.InstallDir); err != nil || !info.IsDir() {
		return block([]string{failedLine("Not installed (" + install.InstallDir + " missing) — nothing to reset.")}), 1
	}
	abs, _ := filepath.Abs(install.InstallDir)
	if filepath.Dir(abs) == abs {
		return block([]string{failedLine("Refusing to use " + install.InstallDir + " as an install directory")}), 1
	}
	envPath := filepath.Join(install.InstallDir, ".env")
	if !fileExists(envPath) {
		return block([]string{failedLine("Config not found: " + envPath + " — install OVManager first.")}), 1
	}

	env := readEnvFile(envPath)
	if dataDir == "" {
		dataDir = strings.Trim(env["DATA_DIR"], `"'`)
	}
	if dataDir == "" {
		return block([]string{failedLine("DATA_DIR is not set in " + envPath + " — cannot locate the database.")}), 1
	}
	owner := strings.Trim(env["ADMIN_USERNAME"], `"'`)
	if owner == "" {
		return block([]string{failedLine("ADMIN_USERNAME is not set — cannot tell which row is the owner.")}), 1
	}

	hashed, err := auth.HashPassword(password)
	if err != nil {
		return block([]string{failedLine("Password hashing is unavailable — " + err.Error())}), 1
	}
	revoked, errMsg := writeOwnerHash(dataDir, hashed, owner)
	if errMsg != "" {
		return block([]string{failedLine(errMsg)}), 1
	}

	rows := []string{
		okLine("owner password updated for " + owner),
		hint("stored in the panel database — .env is not edited"),
	}
	switch {
	case revoked < 0:
		rows = append(rows, hint("could not confirm session revocation — check the panel logs"))
	case revoked == 0:
		rows = append(rows, hint("no active sessions to revoke"))
	default:
		plural := "s"
		if revoked == 1 {
			plural = ""
		}
		rows = append(rows, hint("revoked "+itoa(revoked)+" active session"+plural+" — every device must sign in again"))
	}
	return block(rows), 0
}

// writeOwnerHash sets the owner row's bcrypt hash. Returns (revokedCount,
// errorMessage); revokedCount is -1 when revocation could not be confirmed.
func writeOwnerHash(dataDir, hashed, owner string) (int, string) {
	dbPath := filepath.Join(dataDir, "ovmanager.db")
	if !fileExists(dbPath) {
		return -1, "Panel database not found at " + dbPath + " — is the panel installed?"
	}
	conn, err := db.Open(dbPath)
	if err != nil {
		return -1, "Could not open the panel database: " + err.Error()
	}
	defer conn.Close()

	var id int64
	err = conn.QueryRow(`SELECT id FROM admins WHERE is_owner = 1 LIMIT 1`).Scan(&id)
	if err != nil {
		err = conn.QueryRow(`SELECT id FROM admins WHERE username = ? LIMIT 1`, owner).Scan(&id)
	}
	if err != nil {
		if _, err := conn.Exec(`INSERT INTO admins (username, password, is_owner) VALUES (?, ?, 1)`, owner, hashed); err != nil {
			return -1, "Could not update the owner credential: " + err.Error()
		}
	} else {
		if _, err := conn.Exec(`UPDATE admins SET password = ?, is_owner = 1 WHERE id = ?`, hashed, id); err != nil {
			return -1, "Could not update the owner credential: " + err.Error()
		}
	}

	svc := auth.NewService(conn, dataDir)
	return svc.RevokeUserSessions(owner), ""
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := n < 0
	if neg {
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
