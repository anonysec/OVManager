// `ovmanager reset-password` (cli): rewrite the owner credential in the
// database. Never echoes the value.
package cli

import (
	"os"
	"path/filepath"
	"strings"

	"github.com/anonysec/OVManager/internal/auth"
	"github.com/anonysec/OVManager/internal/db"
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
		dataDir = strings.Trim(env["DataDir"], `"'`)
	}
	if dataDir == "" {
		return block([]string{failedLine("DATA_DIR is not set in " + envPath + " — cannot locate the database.")}), 1
	}
	owner := strings.Trim(env["OwnerUsername"], `"'`)
	if owner == "" {
		return block([]string{failedLine("OwnerUsername is not set — cannot tell which row is the owner.")}), 1
	}

	hashed, err := auth.HashPassword(password)
	if err != nil {
		return block([]string{failedLine("Password hashing is unavailable — " + err.Error())}), 1
	}
	if errMsg := writeOwnerHash(dataDir, hashed, owner); errMsg != "" {
		return block([]string{failedLine(errMsg)}), 1
	}

	rows := []string{
		okLine("owner password updated for " + owner),
		hint("stored in the panel database — .env is not edited"),
	}
	// Sessions live in the panel process, not in the database, so a rewrite
	// from this process cannot end them. Restart the service and say so.
	if ServiceRestart(install) {
		rows = append(rows, hint("all panel sessions ended by the restart — every device must sign in again"))
	} else {
		rows = append(rows, hint("could not restart the panel — run: systemctl restart "+systemdService))
	}
	return block(rows), 0
}

// writeOwnerHash sets the owner row's bcrypt hash and returns an error
// message; the caller ends live sessions by restarting the panel.
func writeOwnerHash(dataDir, hashed, owner string) string {
	dbPath := filepath.Join(dataDir, "app.db")
	if !fileExists(dbPath) {
		return "Panel database not found at " + dbPath + " — is the panel installed?"
	}
	conn, err := db.Open(dbPath)
	if err != nil {
		return "Could not open the panel database: " + err.Error()
	}
	defer conn.Close()

	var id int64
	err = conn.QueryRow(`SELECT id FROM Admin WHERE is_owner = 1 LIMIT 1`).Scan(&id)
	if err != nil {
		err = conn.QueryRow(`SELECT id FROM Admin WHERE username = ? LIMIT 1`, owner).Scan(&id)
	}
	if err != nil {
		if _, err := conn.Exec(`INSERT INTO Admin (username, password, is_owner) VALUES (?, ?, 1)`, owner, hashed); err != nil {
			return "Could not update the owner credential: " + err.Error()
		}
		return ""
	}
	if _, err := conn.Exec(`UPDATE Admin SET password = ?, is_owner = 1 WHERE id = ?`, hashed, id); err != nil {
		return "Could not update the owner credential: " + err.Error()
	}
	return ""
}
