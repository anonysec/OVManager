// `ovmanager doctor --fix` service-account migration (cli/doctor.py fix_service_account).
package cli

import (
	"os"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"time"
)

// fixServiceAccount moves the panel off root: create the account, grant it,
// switch the unit. The unit is edited, not regenerated, and snapshotted first
// so a panel that does not come back can be restored.
//
// This does NOT rewrite ExecStart: the unit runs the Go binary, and
// reverting to a script-based entrypoint would break every native install.
// Only User= is changed and Group= is inserted
// beside it (Group= at the end of the file would land in [Install]).
func fixServiceAccount(install Install, check Check) Check {
	account := panelUser()
	unit := UnitPath()
	if !fileExists(unit) {
		return check
	}
	if _, err := user.Lookup(account); err != nil {
		if !runFix("useradd", "--system", "--no-create-home",
			"--home-dir", install.DataDir, "--shell", "/usr/sbin/nologin",
			"--comment", "OVManager panel service account", account) {
			return Check{check.Name, false, "could not create the " + account + " account", "useradd " + account}
		}
	}
	u, err := user.Lookup(account)
	if err != nil {
		return Check{check.Name, false, "could not look up the " + account + " account", "useradd " + account}
	}
	g, err := user.LookupGroup(account)
	if err != nil {
		return Check{check.Name, false, "could not look up the " + account + " group", "groupadd " + account}
	}
	uid, _ := strconv.Atoi(u.Uid)
	gid, _ := strconv.Atoi(g.Gid)

	raw, err := os.ReadFile(unit) // #nosec G304 // triaged intentional
	if err != nil {
		return check
	}
	body := string(raw)
	if !regexp.MustCompile(`(?m)^User=.*$`).MatchString(body) {
		return Check{check.Name, false, unit + " sets no User=, so there is nothing to change", "add User=" + account}
	}
	if regexp.MustCompile(`(?m)^Group=`).MatchString(body) {
		return Check{check.Name, false, unit + " already sets Group=; change it by hand if it is not " + account,
			"set User=" + account + " and Group=" + account}
	}
	newBody := regexp.MustCompile(`(?m)^User=.*$`).ReplaceAllString(body, "User="+account+"\nGroup="+account)

	snapshot := unit + ".ovmanager-backup"
	if err := copyFilePerm(unit, snapshot, 0o644); err != nil {
		return Check{check.Name, false, "could not snapshot " + unit, "inspect " + snapshot}
	}
	if err := os.WriteFile(unit, []byte(newBody), 0o644); err != nil { // #nosec G703 // systemd unit path from install record G306
		return Check{check.Name, false, "could not write " + unit, "inspect " + snapshot}
	}
	_ = os.Chmod(unit, 0o644) // #nosec G302 // triaged intentional
	chownMode(filepath.Join(install.InstallDir, ".env"), 0, gid, 0o640)
	chownMode(install.InstallDir, 0, gid, 0o750)
	for _, path := range tlsPaths(install) {
		chownMode(path, 0, gid, 0o640)
	}
	if info, err := os.Stat(install.DataDir); err == nil && info.IsDir() {
		_ = filepath.Walk(install.DataDir, func(path string, _ os.FileInfo, err error) error { // #nosec G122 // admin migration over owned data dir
			if err != nil || path == install.DataDir {
				return nil
			}
			_ = os.Chown(path, uid, gid) // #nosec G122 // admin migration over owned data dir
			return nil
		})
		_ = os.Chown(install.DataDir, uid, gid)
		_ = os.Chmod(install.DataDir, 0o700) // #nosec G302 // triaged intentional
	}
	_ = runFix("systemctl", "daemon-reload")
	if !runFix("systemctl", "restart", systemdService) {
		restoreUnit(snapshot, unit)
		return Check{check.Name, false, "migration failed (systemctl restart failed); the unit was restored", "inspect " + snapshot}
	}
	deadline := time.Now().Add(60 * time.Second)
	for time.Now().Before(deadline) {
		if reachable, _ := fetchHealthAny(healthURLs(install), 3*time.Second, install.Cafile()); reachable {
			return checkServiceAccount(install, false)
		}
		time.Sleep(1 * time.Second)
	}
	restoreUnit(snapshot, unit)
	return Check{check.Name, false, "migration failed (the panel did not answer /health within 60s); the unit was restored", "inspect " + snapshot}
}

func restoreUnit(snapshot, unit string) {
	_ = copyFilePerm(snapshot, unit, 0o644)
	_ = runFix("systemctl", "daemon-reload")
	_ = runFix("systemctl", "restart", systemdService)
}

func chownMode(path string, uid, gid int, mode os.FileMode) {
	if _, err := os.Stat(path); err != nil {
		return
	}
	if mode != 0 {
		_ = os.Chmod(path, mode)
	}
	_ = os.Chown(path, uid, gid)
}

func copyFilePerm(src, dst string, mode os.FileMode) error {
	raw, err := os.ReadFile(src) // #nosec G304 // triaged intentional
	if err != nil {
		return err
	}
	if err := os.WriteFile(dst, raw, mode); err != nil { // #nosec G703 // copy between trusted paths
		return err
	}
	return os.Chmod(dst, mode)
}
