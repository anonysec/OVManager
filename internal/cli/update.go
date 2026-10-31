// `ovm update` — the staged update transaction, ported from install.sh
// do_update (Phase 5). backup → stage → maintenance → activate → verify
// (systemd restart + health check against the URL from .env) → commit, with
// automatic failover on a failed candidate.
//
// v1.6.0 gap this fixes: verification of a dev-layout/native install did not
// restart the service before probing, and probed a URL that was not the one the
// panel serves. Here the restart is explicit (systemctl restart / docker
// restart) and the probe is install.HealthURL(), derived from the installed
// .env (scheme from TLS mode, port from PORT), and the reported version must
// match the release being installed.
package cli

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/db"
	"github.com/anonysec/OVManager/go/internal/maintenance"
	"github.com/anonysec/OVManager/go/internal/version"
)

const (
	appSlug        = "ovmanager"
	updateStageDir = ".ovmanager.staging"
	updatePrevDir  = ".ovmanager.previous"
	updateKeep     = 10
	// inTreeDataDirName is the data-dir name install.sh --build (dev install)
	// writes (DATA_DIR=$dest/data). A release layout keeps DATA_DIR at
	// /var/lib/ovmanager, outside the tree, and is left alone.
	inTreeDataDirName = "data"
)

// CaptureDataDir resolves the data directory the update must preserve across
// the tree swap. Precedence mirrors the panel's own resolution: the installed
// .env DATA_DIR wins, then the ambient DATA_DIR, then the resolved install
// value, then the dev-build default <install>/data. inTree reports whether
// that directory lives inside the install tree — only in-tree data is migrated.
func CaptureDataDir(inst Install) (dir string, inTree bool) {
	raw := strings.TrimSpace(inst.Env["DATA_DIR"])
	if raw == "" {
		raw = strings.TrimSpace(os.Getenv("DATA_DIR"))
	}
	if raw == "" {
		raw = strings.TrimSpace(inst.DataDir)
	}
	if raw == "" {
		raw = filepath.Join(inst.InstallDir, inTreeDataDirName)
	}
	dir = filepath.Clean(raw)
	rel, err := filepath.Rel(filepath.Clean(inst.InstallDir), dir)
	return dir, err == nil && rel != "." && rel != ".." &&
		!strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

// MigrateDataIfInTree copies the previous tree's in-tree data dir into the
// freshly extracted tree, but only when the new tree has no data of its own —
// a candidate that ships its own data must not be clobbered. It copies rather
// than moves, so the previous tree stays intact for a failed-verification
// failover. It returns a short description of the decision for the operator log.
func MigrateDataIfInTree(prevDir, newDir string) (string, error) {
	prevData := filepath.Join(prevDir, inTreeDataDirName)
	if !dirHasEntries(prevData) {
		return "no in-tree data dir to carry", nil
	}
	newData := filepath.Join(newDir, inTreeDataDirName)
	if dirHasEntries(newData) {
		return "candidate already has its own data dir — left untouched", nil
	}
	if err := copyTree(prevData, newData); err != nil {
		return "", err
	}
	return fmt.Sprintf("carried %s → %s", prevData, newData), nil
}

// dirHasEntries reports whether path is a directory with at least one entry.
func dirHasEntries(path string) bool {
	entries, err := os.ReadDir(path)
	return err == nil && len(entries) > 0
}

// copyTree recursively copies src into dst, preserving permission bits.
// ponytail: regular files and dirs only — the data dir holds no symlinks; add
// link handling if a release ever ships one.
func copyTree(src, dst string) error {
	return filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		info, err := d.Info()
		if err != nil {
			return err
		}
		if d.IsDir() {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		return copyFilePerm(path, target, info.Mode().Perm())
	})
}

type updateOptions struct {
	dryRun bool
	build  string
	pin    string
}

func repoSlug() string {
	if v := strings.TrimSpace(os.Getenv("OVM_REPO")); v != "" {
		return v
	}
	return "anonysec/OVManager"
}

// releaseAsset is the bare-binary asset the release workflow publishes for the
// running platform (the SPA is embedded in the binary). install.sh fetches the
// same name.
func releaseAsset() string {
	return fmt.Sprintf("%s-%s-%s", appSlug, runtime.GOOS, runtime.GOARCH)
}

func releaseURL(v string) string {
	return fmt.Sprintf("https://github.com/%s/releases/download/v%s/%s", repoSlug(), v, releaseAsset())
}
func releaseChecksumURL(v string) string { return releaseURL(v) + ".sha256" }

func updateStatePath(install Install) string {
	return filepath.Join(install.DataDir, "update-state.json")
}
func updateMarkerPath(install Install) string {
	return filepath.Join(install.DataDir, "update-maintenance")
}
func stagePath(install Install) string {
	return filepath.Join(filepath.Dir(install.InstallDir), updateStageDir)
}
func prevPath(install Install) string {
	return filepath.Join(filepath.Dir(install.InstallDir), updatePrevDir)
}

// writeUpdateState mirrors install.sh update_state: a JSON journal of the
// transaction phase (read by /updater/operation and the recover path).
func writeUpdateState(install Install, phase, from, to, safety string) {
	body := fmt.Sprintf(`{"phase":%q,"from_version":%q,"to_version":%q,"safety_backup":%q,"updated_at":%q,"pid":%d}`,
		phase, from, to, safety, time.Now().UTC().Format(time.RFC3339), os.Getpid())
	_ = os.MkdirAll(install.DataDir, 0o700)
	_ = os.WriteFile(updateStatePath(install), []byte(body), 0o600)
}

func updatePlanLines(install Install, target string) []string {
	return []string{
		fmt.Sprintf("  → v%s update plan", target),
		kv("backup", "safety copy of the panel database"),
		kv("stage", "fetch and verify the release"),
		kv("maintenance", "block background writes"),
		kv("activate", "swap the release tree"),
		kv("verify", "systemctl restart + health check at "+install.HealthURL()),
		kv("commit", "resume writers"),
	}
}

// rootEuid matches the FetchHealth stub pattern: tests swap the root check so
// the orchestrator's guard can be exercised on non-root CI runners.
var UpdateRootEuid = os.Geteuid

func runUpdate(install Install, opt updateOptions, out io.Writer) int {
	if UpdateRootEuid() != 0 {
		fmt.Fprint(out, block([]string{failedLine("Must run as root")}))
		return 1
	}
	info, err := os.Stat(install.InstallDir)
	if err != nil || !info.IsDir() {
		// Recover an interrupted swap: a crash between the two renames leaves
		// the install dir absent and the previous tree holding the only copy.
		prev := prevPath(install)
		pinfo, perr := os.Stat(prev)
		if perr != nil || !pinfo.IsDir() {
			fmt.Fprint(out, block([]string{failedLine("Not installed (" + install.InstallDir + " missing)")}))
			return 1
		}
		if rerr := os.Rename(prev, install.InstallDir); rerr != nil {
			fmt.Fprint(out, block([]string{failedLine("Could not restore the previous release: " + rerr.Error())}))
			return 1
		}
		_ = os.Remove(updateMarkerPath(install))
		// fall through to the normal update with the restored tree
	}

	target := strings.TrimPrefix(strings.TrimSpace(opt.pin), "v")
	from := version.Version
	if reachable, reported := FetchHealth(install.HealthURL(), 5*time.Second, install.Cafile()); reachable && reported != "?" {
		from = reported
	}

	if opt.dryRun {
		lines := updatePlanLines(install, orValue(target, "latest"))
		lines = append(lines, "", hint("dry run — nothing was changed"))
		fmt.Fprint(out, block(lines))
		return 0
	}

	if target == "" {
		latest, err := fetchLatestRelease()
		if err != nil {
			fmt.Fprint(out, block([]string{failedLine("Could not resolve the latest release: " + err.Error())}))
			return 1
		}
		target = latest
	}

	writeUpdateState(install, "preflight", from, target, "")
	fmt.Fprintln(out, kv("backup", "creating safety copy"))
	safety, err := maintenance.CreateBackup(updateKeep, "pre-update", install.DataDir)
	if err != nil || safety == "" {
		fmt.Fprint(out, block([]string{failedLine("Could not create the mandatory pre-update backup")}))
		return 1
	}
	fmt.Fprintln(out, okLine("backup  "+filepath.Base(safety)))
	writeUpdateState(install, "staging", from, target, safety)

	stage := stagePath(install)
	_ = os.RemoveAll(stage)
	if err := os.MkdirAll(stage, 0o755); err != nil { // #nosec G301 // triaged intentional
		fmt.Fprint(out, block([]string{failedLine("Could not create the staging dir: " + err.Error())}))
		return 1
	}
	fmt.Fprintln(out, kv("stage", "fetching v"+target))
	if err := stageRelease(stage, target, opt.build, install); err != nil {
		_ = os.RemoveAll(stage)
		fmt.Fprint(out, block([]string{failedLine(err.Error())}))
		return 1
	}

	// maintenance: block writes
	writeUpdateState(install, "activating", from, target, safety)
	_ = os.WriteFile(updateMarkerPath(install), nil, 0o600)
	fmt.Fprintln(out, kv("maintenance", "writes paused"))
	serviceStop(install)

	// Capture the resolved data dir before the swap: an in-tree DATA_DIR moves
	// with the old tree into .previous and must be carried into the new tree.
	dataDir, inTreeData := CaptureDataDir(install)

	// activate
	prev := prevPath(install)
	_ = os.RemoveAll(prev)
	if err := os.Rename(install.InstallDir, prev); err != nil {
		_ = os.Remove(updateMarkerPath(install))
		writeUpdateState(install, "failed_over", from, target, safety)
		fmt.Fprint(out, block([]string{failedLine("Could not activate the staged release; the previous release remains active and data was not changed")}))
		return 1
	}
	if err := os.Rename(stage, install.InstallDir); err != nil {
		_ = os.Rename(prev, install.InstallDir)
		_ = os.Remove(updateMarkerPath(install))
		writeUpdateState(install, "failed_over", from, target, safety)
		fmt.Fprint(out, block([]string{failedLine("Could not activate the staged release; the previous release remains active and data was not changed")}))
		return 1
	}
	fmt.Fprintln(out, kv("activate", "v"+from+" → v"+target))

	// Carry an in-tree data dir into the freshly extracted tree so the panel
	// keeps its database, claim key, node certs and backups across the swap.
	if inTreeData {
		decision, err := MigrateDataIfInTree(prev, install.InstallDir)
		if err != nil {
			fmt.Fprintln(out, kv("data", "could not carry "+dataDir+": "+err.Error()))
			_ = os.Rename(install.InstallDir, stage)
			if rerr := os.Rename(prev, install.InstallDir); rerr != nil {
				writeUpdateState(install, "recovery_required", from, target, safety)
				fmt.Fprint(out, block([]string{failedLine("Update could not carry the in-tree data dir and could not restore the previous release.")}))
				return 1
			}
			_ = os.RemoveAll(stage)
			_ = os.Remove(updateMarkerPath(install))
			writeUpdateState(install, "failed_over", from, target, safety)
			serviceRestart(install)
			fmt.Fprint(out, block([]string{failedLine("Could not carry the in-tree data dir; the previous release remains active and data was not changed")}))
			return 1
		}
		fmt.Fprintln(out, kv("data", decision))
	} else {
		fmt.Fprintln(out, kv("data", "DATA_DIR outside the install tree — left in place"))
	}

	// verify — the phase the v1.6.0 dev layout skipped.
	writeUpdateState(install, "verifying", from, target, safety)
	fmt.Fprintln(out, kv("verify", "restarting "+systemdService))
	started := serviceRestart(install)
	verified := false
	if started {
		if reachable, reported := waitHealth(install.HealthURL(), 60, install.Cafile()); reachable && reported == target {
			verified = true
		} else if reachable {
			fmt.Fprintln(out, "  warn: candidate reported version '"+reported+"', expected '"+target+"'")
		}
	}

	if !verified {
		fmt.Fprintln(out, kv("verify", "candidate did not answer — failing over to v"+from))
		writeUpdateState(install, "failing_over", from, target, safety)
		serviceStop(install)
		_ = os.RemoveAll(stage)
		_ = os.Rename(install.InstallDir, stage)
		if err := os.Rename(prev, install.InstallDir); err != nil {
			writeUpdateState(install, "recovery_required", from, target, safety)
			fmt.Fprint(out, block([]string{failedLine("Automatic failover could not restore the previous release.")}))
			return 1
		}
		dbRestored := false
		if dbRestoreNeeded(safety, filepath.Join(install.DataDir, "ovmanager.db")) {
			if err := restoreUpdateDatabase(safety, filepath.Join(install.DataDir, "ovmanager.db")); err != nil {
				writeUpdateState(install, "recovery_required", from, target, safety)
				fmt.Fprint(out, block([]string{failedLine("Previous code was restored but the database safety backup could not be restored")}))
				return 1
			}
			dbRestored = true
		}
		if serviceRestart(install) {
			if reachable, _ := waitHealth(install.HealthURL(), 60, install.Cafile()); reachable {
				_ = os.Remove(updateMarkerPath(install))
				writeUpdateState(install, "failed_over", from, target, safety)
				note := " (database was untouched — no restore needed)"
				if dbRestored {
					note = " Data was restored from " + safety + "."
				}
				fmt.Fprint(out, block([]string{failedLine("Update failed over safely to v" + from + "." + note)}))
				return 1
			}
		}
		writeUpdateState(install, "recovery_required", from, target, safety)
		fmt.Fprint(out, block([]string{failedLine("Update recovery needs attention. Safety backup: " + safety)}))
		return 1
	}

	// commit
	fmt.Fprintln(out, kv("commit", "resuming writers"))
	_ = os.Remove(updateMarkerPath(install))
	serviceRestart(install)
	if reachable, _ := waitHealth(install.HealthURL(), 60, install.Cafile()); !reachable {
		_ = os.WriteFile(updateMarkerPath(install), nil, 0o600)
		writeUpdateState(install, "recovery_required", from, target, safety)
		fmt.Fprint(out, block([]string{failedLine("Candidate passed verification but failed its final restart. Writes are blocked; run: ovm update")}))
		return 1
	}
	writeUpdateState(install, "committed", from, target, safety)
	fmt.Fprint(out, block([]string{okLine("v" + from + " → v" + target)}))
	return 0
}

func orValue(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

func fetchLatestRelease() (string, error) {
	client := &http.Client{Timeout: 10 * time.Second}
	req, _ := http.NewRequest(http.MethodGet, "https://api.github.com/repos/"+repoSlug()+"/releases/latest", nil)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var decoded struct {
		TagName string `json:"tag_name"`
	}
	if err := json.Unmarshal(raw, &decoded); err != nil || decoded.TagName == "" {
		return "", fmt.Errorf("GitHub did not report a release")
	}
	return strings.TrimPrefix(strings.TrimSpace(decoded.TagName), "v"), nil
}

// stageRelease fills stage with the release to install, verifying the checksum.
func stageRelease(stage, target, src string, install Install) error {
	if src != "" {
		if src == "." {
			src, _ = os.Getwd()
		}
		if _, err := os.Stat(filepath.Join(src, "cmd", "main.go")); err != nil {
			return fmt.Errorf("no Go source tree in %s", src)
		}
		cmd := exec.Command("rsync", "-a", "--delete", // #nosec G204 // triaged intentional
			"--exclude", ".git", "--exclude", "node_modules", "--exclude", "data",
			"--exclude", ".env", src+"/", stage+"/")
		if out, err := cmd.CombinedOutput(); err != nil {
			return fmt.Errorf("stage failed: %s", strings.TrimSpace(string(out)))
		}
		// A source tree carries no binary: build it, exactly as install.sh
		// does for a --build install. Without this the staged tree has no
		// executable, the service fails to start, and the update rolls back.
		build := exec.Command("go", "build", "-o", filepath.Join(stage, appSlug), "./cmd") // #nosec G204 // triaged intentional
		build.Dir = stage
		if out, err := build.CombinedOutput(); err != nil {
			return fmt.Errorf("build failed: %s", strings.TrimSpace(string(out)))
		}
	} else {
		// Bare-binary release: download the platform binary straight into the
		// stage under the service name, verify it against its .sha256 sidecar,
		// then make it executable. No archive, no extract.
		bin := filepath.Join(stage, appSlug)
		if err := download(releaseURL(target), bin); err != nil {
			return fmt.Errorf("No verified release file is available for v%s", target)
		}
		checksum, err := downloadBytes(releaseChecksumURL(target))
		if err != nil {
			return fmt.Errorf("Release checksum file is missing for v%s", target)
		}
		if err := verifyChecksum(bin, string(checksum)); err != nil {
			return err
		}
		if err := os.Chmod(bin, 0o755); err != nil { // #nosec G302 // triaged intentional
			return err
		}
	}
	// Preserve configuration; drop a retired secret the new tree rejects.
	env, err := os.ReadFile(filepath.Join(install.InstallDir, ".env"))
	if err == nil {
		stripped := stripEnvKey(string(env), "BACKUP_ENCRYPT_KEY")
		_ = os.WriteFile(filepath.Join(stage, ".env"), []byte(stripped), 0o600)
	}
	return nil
}

func stripEnvKey(body, key string) string {
	var out []string
	for _, line := range strings.Split(body, "\n") {
		if strings.HasPrefix(line, key+"=") {
			continue
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}

func download(url, dst string) error {
	resp, err := (&http.Client{Timeout: 5 * time.Minute}).Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	f, err := os.Create(dst) // #nosec G304 // triaged intentional
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(f, resp.Body)
	return err
}

func downloadBytes(url string) ([]byte, error) {
	resp, err := (&http.Client{Timeout: 30 * time.Second}).Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %d", resp.StatusCode)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 1<<20))
}

func verifyChecksum(path, checksumBody string) error {
	want := strings.Fields(strings.TrimSpace(checksumBody))
	if len(want) == 0 {
		return fmt.Errorf("empty checksum file")
	}
	f, err := os.Open(path) // #nosec G304 // triaged intentional
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	got := hex.EncodeToString(h.Sum(nil))
	if !strings.EqualFold(got, want[0]) {
		return fmt.Errorf("Release checksum mismatch")
	}
	return nil
}

// waitHealth polls the URL until it answers, returning the reported version.
func waitHealth(url string, tries int, cafile string) (bool, string) {
	for i := 0; i < tries; i++ {
		if reachable, reported := FetchHealth(url, 3*time.Second, cafile); reachable {
			return true, reported
		}
		time.Sleep(time.Second)
	}
	return false, "?"
}

func serviceRestart(install Install) bool {
	if fileExists(install.ComposeFile()) {
		return runFix("docker", "compose", "-f", install.ComposeFile(), "up", "-d")
	}
	return runFix("systemctl", "restart", systemdService)
}

func serviceStop(install Install) {
	if fileExists(install.ComposeFile()) {
		_ = runFix("docker", "compose", "-f", install.ComposeFile(), "down")
		return
	}
	_ = runFix("systemctl", "stop", systemdService)
}

// dbRestoreNeeded compares the schema version of the live database against the
// safety backup (install.sh db_restore_needed).
func dbRestoreNeeded(backup, live string) bool {
	liveVersion, err := userVersion(live)
	if err != nil {
		return true
	}
	backupVersion, err := userVersion(backup)
	if err != nil {
		return false
	}
	return backupVersion != liveVersion
}

func userVersion(path string) (int, error) {
	conn, err := dbOpenReadOnly(path)
	if err != nil {
		return 0, err
	}
	defer conn.Close()
	var v int
	if err := conn.QueryRow(`PRAGMA user_version`).Scan(&v); err != nil {
		return 0, err
	}
	return v, nil
}

// restoreUpdateDatabase copies the verified backup over the live database
// (install.sh restore_update_database).
func restoreUpdateDatabase(backup, live string) error {
	if !fileExists(backup) {
		return fmt.Errorf("backup missing")
	}
	if _, err := userVersion(backup); err != nil {
		return err
	}
	raw, err := os.ReadFile(backup) // #nosec G304 // triaged intentional
	if err != nil {
		return err
	}
	mode := os.FileMode(0o600)
	var uid, gid = -1, -1
	if info, err := os.Stat(live); err == nil {
		mode = info.Mode().Perm()
		uid, gid = statUID(info), statGID(info)
	}
	tmp := live + ".update-rollback"
	if err := os.WriteFile(tmp, raw, mode); err != nil { // #nosec G703 // tmp beside trusted live path
		return err
	}
	_ = os.Chmod(tmp, mode)
	if uid >= 0 {
		_ = os.Chown(tmp, uid, gid)
	}
	if err := os.Rename(tmp, live); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	for _, suffix := range []string{"-wal", "-shm"} {
		_ = os.Remove(live + suffix)
	}
	return nil
}

func dbOpenReadOnly(path string) (*sql.DB, error) {
	return db.Open(path)
}
