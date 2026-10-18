// Parity tests for plan Task 5: in-panel DB export/import. The endpoints live
// under /api/db/* as thin owner-gated aliases over the maintenance backup
// routes (backupDownload streams the newest stored backup; backupRestore
// walks the atomic staging restore). The tests pin the owner gate, the
// download headers, and the fail-closed multipart restore.
package tests

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/db"
)

// dbUploadCap mirrors the panel's maintenance upload cap (maxBackupFileSize);
// the restore routes stream uploads through writeUploadCapped with it.
const dbUploadCap = 100 * 1024 * 1024

// seedHelperAdmin inserts a non-owner admin row so a plain admin-role session
// can drive the owner-gate cases.
func seedHelperAdmin(t *testing.T, conn *sql.DB) {
	t.Helper()
	if _, err := conn.Exec(
		`INSERT INTO admins (username, password, is_owner) VALUES ('helper', ?, 0)`, pythonBcryptHash,
	); err != nil {
		t.Fatalf("seed helper admin: %v", err)
	}
}

// helperToken mints an admin (non-owner) session for env's database.
func helperToken(t *testing.T, env *panelEnv) string {
	t.Helper()
	svc := auth.NewService(env.conn, env.dataDir)
	tok, err := svc.CreateSession("helper", "admin", "", "", 3600)
	if err != nil {
		t.Fatalf("helper session: %v", err)
	}
	return tok
}

// postMultipartFile fields a multipart upload the way every panel restore
// client does (the file arrives as the "file" form part).
func postMultipartFile(t *testing.T, url, token, field, filename string, content []byte) (*http.Response, map[string]any) {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	part, err := mw.CreateFormFile(field, filename)
	if err != nil {
		t.Fatalf("form file: %v", err)
	}
	if _, err := part.Write(content); err != nil {
		t.Fatalf("write part: %v", err)
	}
	if err := mw.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	res, raw := rawReq(t, "POST", url, token, &buf, mw.FormDataContentType())
	var got map[string]any
	_ = json.Unmarshal(raw, &got)
	return res, got
}

func TestDBBackupRequiresOwner(t *testing.T) {
	env := newPanelEnv(t)
	seedHelperAdmin(t, env.conn)
	admin := helperToken(t, env)

	for _, tc := range []struct{ method, path string }{
		{"GET", "/api/db/backup"}, {"POST", "/api/db/restore"},
	} {
		res, raw := rawReq(t, tc.method, env.srv.URL+tc.path, admin, nil, "")
		if res.StatusCode != 403 {
			t.Fatalf("admin %s %s: status = %d, want 403 (%s)", tc.method, tc.path, res.StatusCode, raw)
		}
		var got map[string]any
		_ = json.Unmarshal(raw, &got)
		if got["detail"] != "This action requires owner privileges" {
			t.Fatalf("admin %s %s: detail = %v", tc.method, tc.path, got["detail"])
		}
	}

	// No credentials at all → 401, same as every owner-only panel route.
	for _, tc := range []struct{ method, path string }{
		{"GET", "/api/db/backup"}, {"POST", "/api/db/restore"},
	} {
		res, _ := rawReq(t, tc.method, env.srv.URL+tc.path, "", nil, "")
		if res.StatusCode != 401 {
			t.Fatalf("anonymous %s %s: status = %d, want 401", tc.method, tc.path, res.StatusCode)
		}
	}
}

func TestDBBackupDownloadLatest(t *testing.T) {
	env := newPanelEnv(t)

	// No backup on disk → the bare {"detail": ...} 404 shape other panel
	// downloads return, not an envelope.
	res, raw := rawReq(t, "GET", env.srv.URL+"/api/db/backup", env.token, nil, "")
	if res.StatusCode != 404 {
		t.Fatalf("no backups: status = %d, want 404 (%s)", res.StatusCode, raw)
	}
	var detail map[string]any
	_ = json.Unmarshal(raw, &detail)
	if _, ok := detail["detail"]; !ok {
		t.Fatalf("no backups body lacks detail: %s", raw)
	}

	// One backup exists → the newest file streams as octet-stream attachment.
	_, createBody := doJSON(t, "POST", env.srv.URL+"/api/maintenance/backup", env.token, nil)
	if createBody["success"] != true {
		t.Fatalf("backup create: %v", createBody)
	}
	files := backupDirFiles(t, env.dataDir)
	if len(files) == 0 {
		t.Fatal("no backup file written")
	}
	want, err := os.ReadFile(files[0])
	if err != nil {
		t.Fatalf("read backup: %v", err)
	}

	res, raw = rawReq(t, "GET", env.srv.URL+"/api/db/backup", env.token, nil, "")
	if res.StatusCode != 200 {
		t.Fatalf("download: status = %d", res.StatusCode)
	}
	if ct := res.Header.Get("Content-Type"); !strings.Contains(ct, "application/octet-stream") {
		t.Fatalf("download content-type = %q", ct)
	}
	disp := res.Header.Get("Content-Disposition")
	if !strings.HasPrefix(disp, `attachment; filename="`) || !strings.HasSuffix(disp, `.db"`) {
		t.Fatalf("download content-disposition = %q", disp)
	}
	if cl, _ := strconv.Atoi(res.Header.Get("Content-Length")); int64(cl) != int64(len(want)) {
		t.Fatalf("content-length = %s, want %d", res.Header.Get("Content-Length"), len(want))
	}
	if !bytes.Equal(raw, want) {
		t.Fatal("download body differs from the newest backup file")
	}
}

// backupDirFiles lists DATA_DIR/backups newest-first (mirrors backupFiles).
func backupDirFiles(t *testing.T, dataDir string) []string {
	t.Helper()
	entries, err := os.ReadDir(filepath.Join(dataDir, "backups"))
	if err != nil {
		t.Fatalf("backups dir: %v", err)
	}
	var out []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".db") {
			out = append(out, filepath.Join(dataDir, "backups", e.Name()))
		}
	}
	return out
}

func TestDBRestoreUploadRoundTrip(t *testing.T) {
	env := newPanelEnv(t)

	// Seed the settings row, take the safety backup, then move a marker
	// column away from its default so the swap is observable.
	doJSON(t, "GET", env.srv.URL+"/api/server/settings", env.token, nil)
	if _, body := doJSON(t, "POST", env.srv.URL+"/api/maintenance/backup", env.token, nil); body["success"] != true {
		t.Fatalf("backup create: %v", body)
	}
	if _, body := doJSON(t, "PUT", env.srv.URL+"/api/server/settings/bot", env.token,
		map[string]any{"default_days": 45}); body["success"] != true {
		t.Fatalf("mark settings: %v", body)
	}
	days := func() int {
		_, body := doJSON(t, "GET", env.srv.URL+"/api/server/settings", env.token, nil)
		data, _ := body["data"].(map[string]any)
		n, _ := data["default_days"].(float64)
		return int(n)
	}
	if days() != 45 {
		t.Fatalf("pre-restore default_days = %d, want 45", days())
	}

	files := backupDirFiles(t, env.dataDir)
	blob, err := os.ReadFile(files[0])
	if err != nil {
		t.Fatalf("read backup: %v", err)
	}

	res, got := postMultipartFile(t, env.srv.URL+"/api/db/restore", env.token,
		"file", "ovmanager-backup-test.db", blob)
	if res.StatusCode != 200 || got["success"] != true {
		t.Fatalf("restore upload: %d %v", res.StatusCode, got)
	}
	data, _ := got["data"].(map[string]any)
	if data["rolled_back"] != false {
		t.Fatalf("restore data = %v", data)
	}
	if s, _ := data["safety_backup"].(string); s == "" {
		t.Fatalf("restore data missing safety_backup: %v", data)
	}

	// The live pool now serves the uploaded database: marker gone.
	if days() != 30 {
		t.Fatalf("post-restore default_days = %d, want 30", days())
	}

	// Audit entry recorded like the tls_acme events. The restore swaps the
	// live handle (env.conn was closed by the activation), so open a fresh
	// reader over the same file.
	audit, err := db.Open(filepath.Join(env.dataDir, "ovmanager.db"))
	if err != nil {
		t.Fatalf("reopen db: %v", err)
	}
	defer audit.Close()
	var n int
	if err := audit.QueryRow(
		`SELECT COUNT(*) FROM audit_logs WHERE action = 'db_restore'`).Scan(&n); err != nil {
		t.Fatalf("audit query: %v", err)
	}
	if n < 1 {
		t.Fatal("no db_restore audit entry")
	}

	// Non-.db uploads are refused before any staging.
	res, got = postMultipartFile(t, env.srv.URL+"/api/db/restore", env.token,
		"file", "notes.txt", []byte("hello"))
	if got["success"] != false {
		t.Fatalf("non-.db upload accepted: %v", got)
	}
	if res.StatusCode != 200 {
		t.Fatalf("non-.db upload status = %d", res.StatusCode)
	}
}

func TestDBRestoreFailClosed(t *testing.T) {
	env := newPanelEnv(t)
	doJSON(t, "PUT", env.srv.URL+"/api/server/settings/bot", env.token,
		map[string]any{"default_days": 45})

	res, got := postMultipartFile(t, env.srv.URL+"/api/db/restore", env.token,
		"file", "garbage.db", []byte("this is definitely not a sqlite database or a zipfile"))
	if res.StatusCode != 200 || got["success"] != false {
		t.Fatalf("garbage upload: %d %v", res.StatusCode, got)
	}
	if msg, _ := got["msg"].(string); !strings.Contains(msg, "Invalid SQLite database") {
		t.Fatalf("garbage upload msg = %q, want the validation message", msg)
	}

	// Live database untouched and still serving.
	_, body := doJSON(t, "GET", env.srv.URL+"/api/server/settings", env.token, nil)
	data, _ := body["data"].(map[string]any)
	if data == nil {
		t.Fatalf("live db broken after failed restore: %v", body)
	}
	if int(data["default_days"].(float64)) != 45 {
		t.Fatalf("default_days after failed restore = %v, want 45 (fail-closed)", data["default_days"])
	}

	// Staging artifacts cleaned up: no candidate temp files, no restore_* uploads.
	entries, err := os.ReadDir(env.dataDir)
	if err != nil {
		t.Fatalf("data dir: %v", err)
	}
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".restore-candidate-") || strings.HasPrefix(e.Name(), ".restore-rollback-") {
			t.Fatalf("staging file left in data dir: %s", e.Name())
		}
	}
	backupEntries, err := os.ReadDir(filepath.Join(env.dataDir, "backups"))
	if err == nil {
		for _, e := range backupEntries {
			if strings.HasPrefix(e.Name(), "restore_") {
				t.Fatalf("restore upload left behind: %s", e.Name())
			}
		}
	}
}

func TestDBRestoreRejectsOversize(t *testing.T) {
	env := newPanelEnv(t)

	// One byte over the existing upload cap, streamed as zeros.
	over := dbUploadCap + 1
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	part, _ := mw.CreateFormFile("file", "big.db")
	block := make([]byte, 1<<20)
	for io0 := 0; io0 < over; io0 += len(block) {
		n := len(block)
		if over-io0 < n {
			n = over - io0
		}
		_, _ = part.Write(block[:n])
	}
	_ = mw.Close()
	res, raw := rawReq(t, "POST", env.srv.URL+"/api/db/restore", env.token,
		&buf, mw.FormDataContentType())
	var got map[string]any
	_ = json.Unmarshal(raw, &got)
	if res.StatusCode != 200 || got["success"] != false {
		t.Fatalf("oversize upload: %d %v", res.StatusCode, got)
	}
	if msg, _ := got["msg"].(string); !strings.Contains(msg, "File too large") {
		t.Fatalf("oversize msg = %q, want the cap detail", msg)
	}

	// The pre-restore flow never ran: no safety backup appeared.
	if files := backupDirFiles(t, env.dataDir); len(files) != 0 {
		t.Fatalf("oversize upload created backups: %v", files)
	}
}

func TestDBRestoreRequiresFile(t *testing.T) {
	env := newPanelEnv(t)
	res, raw := rawReq(t, "POST", env.srv.URL+"/api/db/restore", env.token, nil, "")
	var got map[string]any
	_ = json.Unmarshal(raw, &got)
	if res.StatusCode != 200 || got["success"] != false {
		t.Fatalf("restore without file: %d %v", res.StatusCode, got)
	}
	if msg, _ := got["msg"].(string); msg != "Backup file must be a .db file" {
		t.Fatalf("restore without file msg = %q", msg)
	}
}
