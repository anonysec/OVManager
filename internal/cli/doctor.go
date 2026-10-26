// `ovm doctor` checks and auto-fixes (cli/doctor.py).
package cli

import (
	"encoding/json"
	"fmt"
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

// Check is one diagnostic row.
type Check struct {
	Name   string
	OK     bool
	Detail string
	Fix    string
}

// LegacyBackupDir is the installer's update-tarball directory (a test seam).
var LegacyBackupDir = "/var/backups"

func panelUser() string {
	if v := os.Getenv("OVM_PANEL_USER"); v != "" {
		return v
	}
	return "ovmanager"
}

func checkService(install Install, service string) Check {
	mode, state := ServiceState(install.ComposeFile())
	if service != "" {
		state = service
	}
	ok := state == "running" || state == "running (docker)" || state == "active"
	fix := ""
	if !ok {
		fix = "ovm restart"
	}
	return Check{"Service", ok, state + " (" + mode + ")", fix}
}

func checkAutostart(install Install) Check {
	if fileExists(install.ComposeFile()) {
		return Check{"Auto start", true, "docker (restart policy)", ""}
	}
	enabled := SystemctlEnabled(systemdService)
	detail := "disabled"
	fix := "ovm enable"
	if enabled {
		detail, fix = "enabled", ""
	}
	return Check{"Auto start", enabled, detail, fix}
}

func certEnddate(cert string) (time.Time, bool) {
	out, err := exec.Command("openssl", "x509", "-enddate", "-noout", "-in", cert).Output()
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

func checkCertificate(install Install) Check {
	if install.TLSMode == "none" {
		return Check{"Certificate", true, "not in use (plain HTTP)", ""}
	}
	cert := install.Cafile()
	if cert == "" || !fileExists(cert) {
		return Check{"Certificate", false, "not found", "ovm https"}
	}
	expiry, ok := certEnddate(cert)
	if !ok {
		return Check{"Certificate", false, "could not read expiry", "ovm https"}
	}
	daysLeft := int(expiry.Sub(time.Now().UTC()).Seconds() / 86400)
	switch {
	case daysLeft > 30:
		return Check{"Certificate", true, fmt.Sprintf("expires in %dd", daysLeft), ""}
	case daysLeft > 0:
		return Check{"Certificate", false, fmt.Sprintf("expires in %dd", daysLeft), "ovm https"}
	default:
		return Check{"Certificate", false, "expired", "ovm https"}
	}
}

func checkUpdateJournal(install Install) Check {
	if fileExists(filepath.Join(install.DataDir, "update-maintenance")) {
		return Check{"Update", false, "recovery required", "ovm update"}
	}
	state := filepath.Join(install.DataDir, "update-state.json")
	if fileExists(state) {
		phase := ""
		if raw, err := os.ReadFile(state); err == nil {
			var decoded map[string]any
			if json.Unmarshal(raw, &decoded) == nil {
				phase, _ = decoded["phase"].(string)
			}
		}
		if phase != "committed" && phase != "failed_over" {
			return Check{"Update", false, "recovery required", "ovm update"}
		}
	}
	return Check{"Update", true, "no interrupted transaction", ""}
}

// BackupTimerUnit mirrors the unit install.sh writes: <service stem>-backup.timer.
// It is a test seam so host state cannot make doctor tests flaky.
var BackupTimerUnit = func(install Install) string {
	base := filepath.Base(install.InstallDir)
	return "/etc/systemd/system/" + base + "-backup.timer"
}

func checkBackupAge(install Install, maximumDays int) Check {
	var candidates []string
	backups := filepath.Join(install.DataDir, "backups")
	if entries, err := os.ReadDir(backups); err == nil {
		for _, e := range entries {
			if strings.HasSuffix(e.Name(), ".db") {
				candidates = append(candidates, filepath.Join(backups, e.Name()))
			}
		}
	}
	if entries, err := os.ReadDir(LegacyBackupDir); err == nil {
		for _, e := range entries {
			if strings.HasPrefix(e.Name(), "panel-") && strings.HasSuffix(e.Name(), ".tar.gz") {
				candidates = append(candidates, filepath.Join(LegacyBackupDir, e.Name()))
			}
		}
	}
	if len(candidates) == 0 {
		// A configured daily timer covers this — backups will exist after its
		// first tick, and no manual reminder is warranted meanwhile.
		if fileExists(BackupTimerUnit(install)) {
			return Check{"Backup", true, "scheduled (daily timer)", ""}
		}
		return Check{"Backup", false, "none yet", "ovm backup"}
	}
	newest := candidates[0]
	var newestMod time.Time
	for _, p := range candidates {
		if info, err := os.Stat(p); err == nil && (newestMod.IsZero() || info.ModTime().After(newestMod)) {
			newest, newestMod = p, info.ModTime()
		}
	}
	ageDays := int(time.Since(newestMod).Hours() / 24)
	_ = newest
	ok := ageDays <= maximumDays
	fix := ""
	if !ok {
		fix = "ovm backup"
	}
	return Check{"Backup", ok, fmt.Sprintf("%dd old", ageDays), fix}
}

func checkPrivatePermissions(install Install) Check {
	if fileExists(install.ComposeFile()) {
		return Check{"Permissions", true, "container-managed", ""}
	}
	var loose []string
	if !isMode(install.DataDir, 0o700) {
		loose = append(loose, "data dir")
	}
	backups := filepath.Join(install.DataDir, "backups")
	if info, err := os.Stat(backups); err == nil && info.IsDir() && !isMode(backups, 0o700) {
		loose = append(loose, "backups dir")
	}
	for _, name := range []string{"ovmanager.db", "update-state.json", "update-maintenance"} {
		path := filepath.Join(install.DataDir, name)
		if fileExists(path) && !isMode(path, 0o600) {
			loose = append(loose, name)
		}
	}
	if len(loose) == 0 {
		return Check{"Permissions", true, "private", ""}
	}
	return Check{"Permissions", false, "loose (" + strings.Join(loose, ", ") + ")", "ovm doctor --fix"}
}

func isMode(path string, mode os.FileMode) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return info.Mode().Perm() == mode
}

func checkDisk(path string) Check {
	free, ok := DiskFreeMB(path)
	if !ok {
		return Check{"Disk", false, path + " unreadable", "free disk space"}
	}
	if free >= 200 {
		return Check{"Disk", true, fmt.Sprintf("%d MB free", free), ""}
	}
	return Check{"Disk", false, fmt.Sprintf("%d MB free", free), "free disk space"}
}

func checkEnvPerms(install Install, inContainer bool) Check {
	path := filepath.Join(install.InstallDir, ".env")
	if inContainer {
		return Check{"Config perms", true, "n/a (host-managed)", ""}
	}
	if !fileExists(path) {
		return Check{"Config perms", false, ".env missing", "reinstall"}
	}
	if fileExists(install.ComposeFile()) {
		return checkEnvSharedWithContainer(path)
	}
	mode := isModeVal(path)
	gid := statGid(path)
	if mode == 0o600 {
		return Check{"Config perms", true, fmt.Sprintf(".env is %s", octal(mode)), ""}
	}
	service := unitUser()
	if service != "" && mode == 0o640 && groupName(gid) == service {
		return Check{"Config perms", true, octal(mode) + ", shared with " + service, ""}
	}
	detail := fmt.Sprintf(".env is %s owned by group %d (%s)", octal(mode), gid, orUnknown(groupName(gid)))
	if service != "" {
		detail += fmt.Sprintf(", expected 0640 group %s", service)
	} else {
		detail += ", expected 0600"
	}
	fix := "chmod 600 .env"
	if service != "" {
		fix = fmt.Sprintf("chgrp %s .env && chmod 640 .env", service)
	}
	return Check{"Config perms", false, detail, fix}
}

func checkEnvSharedWithContainer(path string) Check {
	if !fileExists(path) {
		return Check{"Config perms", false, ".env missing", "reinstall"}
	}
	mode := isModeVal(path)
	gid := statGid(path)
	if mode&0o040 != 0 && gid != 0 {
		return Check{"Config perms", true, fmt.Sprintf("shared with the container (%s, gid %d)", octal(mode), gid), ""}
	}
	return Check{"Config perms", false, fmt.Sprintf("unreadable by the container (mode %s, gid %d)", octal(mode), gid),
		"sudo ovm update, or chgrp <image ovpanel gid> .env && chmod 640 .env"}
}

func checkTLSKeyPerms(install Install, inContainer bool) Check {
	if inContainer {
		return Check{"TLS key", true, "n/a (container-mounted)", ""}
	}
	key := strings.TrimSpace(envFile(install)["SSL_KEYFILE"])
	if key == "" {
		return Check{"TLS key", true, "n/a (panel-managed or not set)", ""}
	}
	info, err := os.Stat(key)
	if err != nil {
		return Check{"TLS key", false, key + " is missing", "ovm https --self"}
	}
	mode := info.Mode().Perm()
	service := unitUser()
	if service == "" {
		return Check{"TLS key", true, octal(uint32(mode)) + " (panel runs as root)", ""}
	}
	if ownerName(statUID(info)) == service && mode&0o400 != 0 {
		return Check{"TLS key", true, octal(uint32(mode)) + ", owner " + service, ""}
	}
	if groupName(statGID(info)) == service && mode&0o040 != 0 {
		return Check{"TLS key", true, octal(uint32(mode)) + ", shared with " + service, ""}
	}
	owner := orUnknown(ownerName(statUID(info)))
	group := orUnknown(groupName(statGID(info)))
	fix := fmt.Sprintf("chgrp %s %s && chmod 640 %s", service, key, key)
	return Check{"TLS key", false, fmt.Sprintf("%s is %s %s:%s, so %s cannot read it", key, octal(uint32(mode)), owner, group, service), fix}
}

func checkDataDir(install Install) Check {
	info, err := os.Stat(install.DataDir)
	ok := err == nil && info.IsDir()
	fix := ""
	if !ok {
		fix = "reinstall"
	}
	return Check{"Data dir", ok, install.DataDir, fix}
}

func checkHealth(install Install) Check {
	reachable, version := FetchHealth(install.HealthURL(), 5*time.Second, install.Cafile())
	if reachable {
		return Check{"Panel health", true, "ok (v" + version + ")", ""}
	}
	return Check{"Panel health", false, "unreachable", "ovm logs"}
}

func checkServiceAccount(install Install, inContainer bool) Check {
	if inContainer || fileExists(install.ComposeFile()) {
		return Check{"Service account", true, "container-managed", ""}
	}
	raw, err := os.ReadFile(UnitPath())
	if err != nil {
		return Check{"Service account", true, "no unit file (not a systemd install)", ""}
	}
	userName := "root"
	for _, line := range strings.Split(string(raw), "\n") {
		if strings.HasPrefix(line, "User=") {
			userName = strings.TrimSpace(strings.TrimPrefix(line, "User="))
			break
		}
	}
	if userName == "root" {
		return Check{"Service account", false, "the panel runs as root",
			fmt.Sprintf("ovm doctor --fix   # moves it onto the %s account", panelUser())}
	}
	return Check{"Service account", true, "panel runs as " + userName, ""}
}

func collectDoctor(install Install, service string, inContainer bool) []Check {
	return []Check{
		checkService(install, service),
		checkAutostart(install),
		checkCertificate(install),
		checkUpdateJournal(install),
		checkBackupAge(install, 7),
		checkPrivatePermissions(install),
		checkDisk(install.DataDir),
		checkEnvPerms(install, inContainer),
		checkTLSKeyPerms(install, inContainer),
		checkDataDir(install),
		checkHealth(install),
		checkServiceAccount(install, inContainer),
	}
}

func runFix(argv ...string) bool {
	cmd := exec.Command(argv[0], argv[1:]...)
	return cmd.Run() == nil
}

func fixCheck(check Check, install Install, service string) Check {
	if check.OK {
		return check
	}
	compose := fileExists(install.ComposeFile())
	switch check.Name {
	case "Service":
		ok := false
		if compose {
			ok = runFix("docker", "restart", "-t", "10", "ovmanager")
		} else {
			ok = runFix("systemctl", "restart", systemdService)
		}
		if ok {
			return checkService(install, service)
		}
		return check
	case "Auto start":
		ok := false
		if compose {
			ok = runFix("docker", "update", "--restart", "unless-stopped", "ovmanager")
		} else {
			ok = runFix("systemctl", "enable", systemdService)
		}
		if ok {
			return checkAutostart(install)
		}
		return check
	case "Permissions":
		for _, p := range []string{install.DataDir, filepath.Join(install.DataDir, "backups")} {
			if info, err := os.Stat(p); err == nil && info.IsDir() {
				_ = os.Chmod(p, 0o700)
			}
		}
		for _, name := range []string{"ovmanager.db", "update-state.json", "update-maintenance"} {
			p := filepath.Join(install.DataDir, name)
			if fileExists(p) {
				_ = os.Chmod(p, 0o600)
			}
		}
		return checkPrivatePermissions(install)
	case "Config perms":
		path := filepath.Join(install.InstallDir, ".env")
		if !fileExists(path) {
			return check
		}
		if os.Chmod(path, 0o600) == nil && isModeVal(path) == 0o600 {
			return Check{check.Name, true, ".env is 0o600 (fixed)", ""}
		}
		return check
	case "TLS key":
		key := strings.TrimSpace(envFile(install)["SSL_KEYFILE"])
		account := unitUser()
		if key == "" || account == "" || !fileExists(key) {
			return check
		}
		gid := groupGID(account)
		if gid < 0 {
			return check
		}
		if os.Chown(key, -1, gid) != nil || os.Chmod(key, 0o640) != nil {
			return check
		}
		return checkTLSKeyPerms(install, false)
	case "Service account":
		return fixServiceAccount(install, check)
	}
	return check
}

func fixAll(install Install, service string, inContainer bool) []Check {
	checks := collectDoctor(install, service, inContainer)
	for _, c := range checks {
		if c.Name == "Service account" {
			fixCheck(c, install, service)
			break
		}
	}
	out := make([]Check, 0, len(checks))
	for _, c := range collectDoctor(install, service, inContainer) {
		out = append(out, fixCheck(c, install, service))
	}
	return out
}

func renderDoctor(checks []Check, showAll bool) string {
	var failed []Check
	for _, c := range checks {
		if !c.OK {
			failed = append(failed, c)
		}
	}
	passed := len(checks) - len(failed)
	if len(failed) == 0 {
		return block([]string{okLine(fmt.Sprintf("no problems — %d checks passed", passed)), hint("detail: ovm doctor --all")})
	}
	lines := []string{failedLine(fmt.Sprintf("%d problems", len(failed))), ""}
	for _, c := range failed {
		lines = append(lines, kv(c.Name, c.Detail))
		if c.Fix != "" {
			lines = append(lines, kv("fix", c.Fix))
		}
	}
	if showAll || passed == 0 {
		lines = append(lines, "", heading("all checks"))
		width := rowsWidth(namesOnly(checks))
		for _, c := range checks {
			mark := "FAIL"
			if c.OK {
				mark = "ok"
			}
			lines = append(lines, fmt.Sprintf("  %s  %s  %s", pad(c.Name, width), mark, c.Detail))
		}
	} else {
		lines = append(lines, "", hint(fmt.Sprintf("%d other checks passed — detail: ovm doctor --all", passed)))
	}
	return block(lines)
}

func namesOnly(checks []Check) [][2]string {
	out := make([][2]string, 0, len(checks))
	for _, c := range checks {
		out = append(out, [2]string{c.Name, ""})
	}
	return out
}

// --- small helpers ---

func octal(mode uint32) string { return "0o" + strconv.FormatUint(uint64(mode), 8) }

func orUnknown(name string) string {
	if name == "" {
		return "unknown"
	}
	return name
}

func isModeVal(path string) uint32 {
	info, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return uint32(info.Mode().Perm())
}

func statGid(path string) int {
	info, err := os.Stat(path)
	if err != nil {
		return -1
	}
	return statGID(info)
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

func groupName(gid int) string {
	if gid < 0 {
		return ""
	}
	g, err := user.LookupGroupId(strconv.Itoa(gid))
	if err != nil {
		return ""
	}
	return g.Name
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

func ownerName(uid int) string {
	if uid < 0 {
		return ""
	}
	u, err := user.LookupId(strconv.Itoa(uid))
	if err != nil {
		return ""
	}
	return u.Username
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
