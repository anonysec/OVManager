package telemetry

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/crypto"
	"github.com/anonysec/OVManager/go/internal/notify"
	_ "modernc.org/sqlite"
)

func TestSendTelegramUsesEncryptedToken(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)

	db, err := sql.Open("sqlite", filepath.Join(dir, "ovmanager.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if _, err := db.Exec(`CREATE TABLE settings (id INTEGER PRIMARY KEY, bot_enabled INTEGER, owner_telegram_id INTEGER, bot_token TEXT)`); err != nil {
		t.Fatal(err)
	}
	enc, err := crypto.EncryptSecret("123456:secret-token", dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`INSERT INTO settings (id, bot_enabled, owner_telegram_id, bot_token) VALUES (1, 1, 42, ?)`, enc); err != nil {
		t.Fatal(err)
	}

	var seenPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seenPath = r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": map[string]any{}})
	}))
	defer srv.Close()
	notify.APIBase = srv.URL

	if !sendTelegram(db, "hello") {
		t.Fatal("sendTelegram returned false for encrypted token")
	}
	if !strings.Contains(seenPath, "secret-token") {
		t.Fatalf("telegram API path did not use decrypted token: %q", seenPath)
	}
}
