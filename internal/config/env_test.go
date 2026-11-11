// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestParseEnvAndEnvOrFile(t *testing.T) {
	raw := `
# Comment line
Port=2095
Host="127.0.0.1"
DataDir='/var/lib/ovmanager'
SPACED = value_with_spaces
`
	parsed := ParseEnv(raw)
	if parsed["Port"] != "2095" {
		t.Errorf("Port = %q, want 2095", parsed["Port"])
	}
	if parsed["Host"] != "127.0.0.1" {
		t.Errorf("Host = %q, want 127.0.0.1", parsed["Host"])
	}
	if parsed["DataDir"] != "/var/lib/ovmanager" {
		t.Errorf("DataDir = %q, want /var/lib/ovmanager", parsed["DataDir"])
	}
	if parsed["SPACED"] != "value_with_spaces" {
		t.Errorf("SPACED = %q, want value_with_spaces", parsed["SPACED"])
	}

	// Test EnvOrFile precedence: process env wins over .env file
	tmp := t.TempDir()
	envPath := filepath.Join(tmp, ".env")
	if err := os.WriteFile(envPath, []byte("MY_KEY=from_file\n"), 0o600); err != nil {
		t.Fatal(err)
	}

	t.Setenv("OVM_APP_DIR", tmp)
	t.Setenv("MY_KEY", "from_process_env")

	if got := EnvOrFile("MY_KEY", "fallback"); got != "from_process_env" {
		t.Fatalf("expected process env to win over file, got %q", got)
	}

	// When process env is unset, file wins over fallback
	t.Setenv("MY_KEY", "")
	if got := EnvOrFile("MY_KEY", "fallback"); got != "from_file" {
		t.Fatalf("expected file value when process env unset, got %q", got)
	}
}
