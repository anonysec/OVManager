package node

import (
	"encoding/json"
	"path/filepath"
	"testing"

	"github.com/anonysec/OVManager/internal/db"
)

func TestValidateNodeSettings(t *testing.T) {
	if err := validateNodeSettings(nil); err != nil {
		t.Fatalf("empty settings rejected: %v", err)
	}
	if err := validateNodeSettings(json.RawMessage(`{"Protocol":"both","MaxClients":500}`)); err != nil {
		t.Fatalf("valid settings rejected: %v", err)
	}
	if err := validateNodeSettings(json.RawMessage(`[1,2]`)); err == nil {
		t.Fatal("array accepted as settings")
	}
	if err := validateNodeSettings(json.RawMessage(`{"x":"` + string(make([]byte, 70<<10)) + `"}`)); err == nil {
		t.Fatal("oversized settings accepted")
	}
}

func TestNodeRowStoresAndReturnsSettings(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("DATA_DIR", dir)
	conn, err := db.Open(filepath.Join(dir, "app.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := db.Migrate(conn); err != nil {
		t.Fatal(err)
	}
	req := nodeCreate{
		Name: "settings-node", Address: "203.0.113.10", Protocol: "both",
		OVPNPort: 443, Port: 2083, Settings: json.RawMessage(`{"MaxClients":500,"TlsMin":"1.3"}`),
	}
	id, err := createNode(conn, req, "PEM")
	if err != nil {
		t.Fatal(err)
	}
	n := GetNodeByID(conn, id)
	if n == nil {
		t.Fatal("node not found")
	}
	if n.Protocol != "both" {
		t.Fatalf("protocol = %q", n.Protocol)
	}
	var stored map[string]any
	if err := json.Unmarshal([]byte(n.Settings), &stored); err != nil {
		t.Fatalf("settings not valid JSON: %v", err)
	}
	if stored["MaxClients"] != float64(500) {
		t.Fatalf("settings = %v", stored)
	}
	for _, row := range listNodes(conn) {
		if row["id"] == id {
			obj, ok := row["settings"].(map[string]any)
			if !ok || obj["TlsMin"] != "1.3" {
				t.Fatalf("list settings = %#v", row["settings"])
			}
		}
	}
}
