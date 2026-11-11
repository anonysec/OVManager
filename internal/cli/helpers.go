package cli

import (
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/anonysec/OVManager/internal/db"
)

func certEnddate(cert string) (time.Time, bool) {
	out, err := exec.Command("openssl", "x509", "-enddate", "-noout", "-in", cert).Output() // #nosec G204 // command arguments are static or validated against strict allowlist
	if err != nil {
		return time.Time{}, false
	}
	m := regexp.MustCompile(`(?m)^notAfter=(.*)$`).FindSubmatch(out)
	if m == nil {
		return time.Time{}, false
	}
	for _, layout := range []string{"Jan _2 15:04:05 2006 MST", "Jan 2 15:04:05 2006 MST"} {
		if t, err := time.Parse(layout, strings.TrimSpace(string(m[1]))); err == nil {
			return t.UTC(), true
		}
	}
	return time.Time{}, false
}

func runFix(argv ...string) bool {
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // command arguments are static or validated against strict allowlist
	return cmd.Run() == nil
}

func unitUserImpl() string {
	raw, err := os.ReadFile(UnitPath())
	if err != nil {
		return ""
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if strings.HasPrefix(line, "User=") {
			u := strings.TrimSpace(strings.TrimPrefix(line, "User="))
			if u == "root" {
				return ""
			}
			return u
		}
	}
	return ""
}

var UnitUser = unitUserImpl

func unitUser() string { return UnitUser() }

func groupGID(name string) int {
	g, err := user.LookupGroup(name)
	if err != nil {
		return -1
	}
	n, err := strconv.Atoi(g.Gid)
	if err != nil {
		return -1
	}
	return n
}

func statUID(info os.FileInfo) int {
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		return int(st.Uid)
	}
	return -1
}

func statGID(info os.FileInfo) int {
	if st, ok := info.Sys().(*syscall.Stat_t); ok {
		return int(st.Gid)
	}
	return -1
}

// repairDBOwnership restores the panel service account's ownership and 0600
// mode on a freshly activated database. Root-run restores otherwise leave
// the file owned by root and unreadable by ovmanager.
func repairDBOwnership(path string) {
	if os.Geteuid() != 0 {
		return
	}
	account := unitUser()
	if account == "" {
		return
	}
	u, err := user.Lookup(account)
	if err != nil {
		return
	}
	uid, err := strconv.Atoi(u.Uid)
	if err != nil {
		return
	}
	gid := groupGID(account)
	if gid < 0 {
		return
	}
	_ = os.Chown(path, uid, gid)
	_ = os.Chmod(path, 0o600)
	for _, suffix := range []string{"-wal", "-shm"} {
		if info, err := os.Stat(path + suffix); err == nil && !info.IsDir() {
			_ = os.Chown(path+suffix, uid, gid)
			_ = os.Chmod(path+suffix, 0o600)
		}
	}
}

func serviceIsRunning() bool {
	_, state := ServiceState()
	s := strings.ToLower(strings.TrimSpace(state))
	return s == "active" || s == "running" || s == "activating" || s == "reloading"
}

func restoreServiceOwned() bool {
	mode, _ := ServiceState()
	return mode == "native"
}

func waitForServiceStopped() bool {
	for i := 0; i < 20; i++ {
		if !serviceIsRunning() {
			return true
		}
		time.Sleep(50 * time.Millisecond)
	}
	return !serviceIsRunning()
}

func restoreDBPath(install Install) string {
	oldData := os.Getenv("DataDir")
	oldApp := os.Getenv("OVM_APP_DIR")
	if install.InstallDir != "" {
		_ = os.Setenv("OVM_APP_DIR", install.InstallDir)
	}
	if install.DataDir != "" {
		_ = os.Setenv("DataDir", install.DataDir)
	}
	cfg := db.ConfigFromEnv()
	path := cfg.Path
	if path == "" {
		path = filepath.Join(install.DataDir, "app.db")
	}
	if oldData == "" {
		_ = os.Unsetenv("DataDir")
	} else {
		_ = os.Setenv("DataDir", oldData)
	}
	if oldApp == "" {
		_ = os.Unsetenv("OVM_APP_DIR")
	} else {
		_ = os.Setenv("OVM_APP_DIR", oldApp)
	}
	return path
}
