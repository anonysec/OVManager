package panel

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"

	"github.com/anonysec/OVManager/go/internal/auth"
)

// cryptoRead fills b with random bytes (used by the audit event key).
func cryptoRead(b []byte) (int, error) { return rand.Read(b) }

// readAtMost reads at most limit bytes, mirroring
// `await file.read(MAX + 1)` size probing.
func readAtMost(r io.Reader, limit int) ([]byte, error) {
	buf := make([]byte, 0, 4096)
	chunk := make([]byte, 4096)
	for len(buf) < limit {
		n, err := r.Read(chunk)
		if n > 0 {
			buf = append(buf, chunk[:n]...)
			if len(buf) > limit {
				buf = buf[:limit]
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return buf, nil
			}
			return buf, err
		}
	}
	return buf, nil
}

// decodeRawBody decodes a JSON body without writing an error response (the
// alert-test route treats a missing body as "no payload").
func decodeRawBody(r *http.Request, dst any) error {
	return json.NewDecoder(r.Body).Decode(dst)
}

// auth404 is FastAPI's HTTPException(404, detail): the bare {"detail": ...}
// body rather than the ResponseModel envelope.
func auth404(w http.ResponseWriter, msg string) {
	auth.WriteDetail(w, http.StatusNotFound, msg)
}

// writeValidationError writes FastAPI's 422 error-list shape with an explicit
// error type.
func writeValidationError(w http.ResponseWriter, kind, field, msg string) {
	auth.WriteJSON(w, http.StatusUnprocessableEntity, map[string]any{
		"detail": []map[string]any{{
			"type": kind, "loc": []any{"body", field}, "msg": msg,
		}},
	})
}

// offsiteTargetRe is the accepted shape of an offsite backup target:
// [user@]host:/absolute/path
var offsiteTargetRe = regexp.MustCompile(`^([A-Za-z0-9._-]+@)?([A-Za-z0-9._-]+):(/[\w./-]+)$`)

// removeMultipartTemps deletes the files the multipart parser spooled to the
// system temp dir: a file part larger than the in-memory limit is written
// there, and the request never removes it on its own. Without this every
// upload leaves a copy of its payload behind in /tmp.
func removeMultipartTemps(r *http.Request) {
	if r.MultipartForm != nil {
		_ = r.MultipartForm.RemoveAll()
	}
}

// ParseOffsiteTarget splits [user@]host:/path and rejects anything else.
//
// The host is restricted to letters, digits, dot, dash and underscore, and
// the path to word characters, slashes, dots and dashes. A ".." segment is
// refused: the target is handed to rsync/scp, which run the remote side
// through a shell, so a path that walks out of the intended folder would
// write somewhere the operator did not name. A leading dash is refused too:
// rsync and scp hand the host to ssh, which would read "-oProxyCommand=..."
// as an option rather than a host.
func ParseOffsiteTarget(target string) (user, host, path string, err error) {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return "", "", "", errors.New("Offsite backup target is empty")
	}
	match := offsiteTargetRe.FindStringSubmatch(trimmed)
	if match == nil {
		return "", "", "", errors.New(
			"Offsite backup target must look like user@server:/path/to/backups (absolute path, no special characters)")
	}
	for _, segment := range strings.Split(match[3], "/") {
		if segment == ".." {
			return "", "", "", errors.New("Offsite backup target must not contain '..'")
		}
	}
	if strings.HasPrefix(match[2], "-") || strings.HasPrefix(match[1], "-") {
		return "", "", "", errors.New("Offsite backup target must not start with '-'")
	}
	return strings.TrimSuffix(match[1], "@"), match[2], match[3], nil
}

// detachSysProcAttr detaches a spawned restart from this process (setsid).
func detachSysProcAttr() *syscall.SysProcAttr { return &syscall.SysProcAttr{Setsid: true} }

// Offsite backup copies are not implemented: the SSH/rsync copy that this
// setting used to advertise was never wired up. Re-adding the control
// requires a real implementation; do not re-add the dead helper here.

// safeFilename is maintenance._safe_filename: basename + ASCII allowlist.
func safeFilename(name string) string {
	if name == "" {
		return ""
	}
	base := filepath.Base(strings.ReplaceAll(name, "\\", "/"))
	base = strings.ReplaceAll(base, "\x00", "")
	var out strings.Builder
	for _, r := range base {
		if r < 0x80 && (isAlnum(r) || r == '.' || r == '_' || r == '-') {
			out.WriteRune(r)
		}
	}
	cleaned := out.String()
	if cleaned == "" || strings.Trim(cleaned, ".") == "" {
		return ""
	}
	return cleaned
}

func isAlnum(r rune) bool {
	return (r >= '0' && r <= '9') || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
}

// copyFile is shutil.copy2 for the backup/restore paths.
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil {
		return err
	}
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, info.Mode().Perm())
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Sync(); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

// stageFile copies src into a temp file beside dst and returns the temp path.
// The destination is NOT touched: the copy happens while the live database is
// still being served, so a 100 MB restore does not spend seconds with the
// pool closed. On any failure the temp file is removed and dst is untouched.
//
// commitStaged renames the staged file over dst. The rename is atomic, and
// the directory is fsynced so the rename itself survives a crash.
func stageFile(src, dst string) (string, error) {
	in, err := os.Open(src)
	if err != nil {
		return "", err
	}
	defer in.Close()
	info, err := in.Stat()
	if err != nil {
		return "", err
	}
	dir := filepath.Dir(dst)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return "", err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(dst)+".*.tmp")
	if err != nil {
		return "", err
	}
	name := tmp.Name()
	cleanup := func() { _ = os.Remove(name) }
	if err := tmp.Chmod(info.Mode().Perm()); err != nil {
		tmp.Close()
		cleanup()
		return "", err
	}
	if _, err := io.Copy(tmp, in); err != nil {
		tmp.Close()
		cleanup()
		return "", err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		cleanup()
		return "", err
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return "", err
	}
	return name, nil
}

// commitStaged renames a staged file over dst and fsyncs the directory, so
// both the file contents and the rename survive a crash.
func commitStaged(tmp, dst string) error {
	if err := os.Rename(tmp, dst); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	dir, err := os.Open(filepath.Dir(dst))
	if err != nil {
		return nil // the rename happened; the directory fsync is best-effort
	}
	defer dir.Close()
	_ = dir.Sync()
	return nil
}

// panelActor is the username of the authenticated caller, for the audit
// trail.
func panelActor(h *Handler, r *http.Request) string {
	if ident, ok := h.Svc.CurrentUser(r); ok {
		return ident.Username
	}
	return "system"
}
