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
)

func certEnddate(cert string) (time.Time, bool) {
	out, err := exec.Command("openssl", "x509", "-enddate", "-noout", "-in", cert).Output() // #nosec G204 // triaged intentional
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
	cmd := exec.Command(argv[0], argv[1:]...) // #nosec G204 // triaged intentional
	return cmd.Run() == nil
}

func envFile(install Install) map[string]string {
	return readEnvFile(filepath.Join(install.InstallDir, ".env"))
}

func tlsPaths(install Install) []string {
	env := envFile(install)
	var found []string
	for _, name := range []string{"SSL_KEYFILE", "SSL_CERTFILE"} {
		if v := strings.TrimSpace(env[name]); v != "" && fileExists(v) {
			found = append(found, v)
		}
	}
	return found
}

func unitUser() string {
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
