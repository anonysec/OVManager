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

// cryptoRead fills b with random bytes (used by the audit event key and the
// placeholder ACME email).
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

// writeValidationBody writes FastAPI's 422 error-list shape for a missing
// multipart field.
func writeValidationBody(w http.ResponseWriter, field, msg string) {
	auth.WriteJSON(w, http.StatusUnprocessableEntity, map[string]any{
		"detail": []map[string]any{{
			"type": "missing", "loc": []any{"body", field}, "msg": msg,
		}},
	})
}

// detachSysProcAttr detaches a spawned restart from this process (setsid).
func detachSysProcAttr() *syscall.SysProcAttr { return &syscall.SysProcAttr{Setsid: true} }

// offsiteTargetRe is backend/operations/backup/offsite.TARGET_RE.
var offsiteTargetRe = regexp.MustCompile(`^([A-Za-z0-9._-]+@)?([A-Za-z0-9._-]+):(/[\w./-]+)$`)

// parseOffsiteTarget splits [user@]host:/path and rejects anything else.
func parseOffsiteTarget(target string) (user, host, path string, err error) {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return "", "", "", errors.New("Offsite backup target is empty")
	}
	match := offsiteTargetRe.FindStringSubmatch(trimmed)
	if match == nil {
		return "", "", "", errors.New(
			"Offsite backup target must look like user@server:/path/to/backups (absolute path, no special characters)")
	}
	return strings.TrimSuffix(match[1], "@"), match[2], match[3], nil
}

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
	return out.Close()
}
