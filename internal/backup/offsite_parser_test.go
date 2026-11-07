package backup

import "testing"

func TestParseOffsiteTarget(t *testing.T) {
	ok := []struct {
		in               string
		user, host, path string
	}{
		{"user@server:/backups", "user", "server", "/backups"},
		{"server:/backups", "", "server", "/backups"},
		{"  ops@db-1.example.com:/var/lib/backups/  ", "ops", "db-1.example.com", "/var/lib/backups/"},
	}
	for _, tc := range ok {
		user, host, path, err := ParseOffsiteTarget(tc.in)
		if err != nil {
			t.Fatalf("%q: %v", tc.in, err)
		}
		if user != tc.user || host != tc.host || path != tc.path {
			t.Fatalf("%q = (%q,%q,%q), want (%q,%q,%q)", tc.in, user, host, path, tc.user, tc.host, tc.path)
		}
	}
	bad := []string{
		"",
		"server:relative/path",
		"server:/backups/../etc",
		"-evil:/backups",
		"user@server:/back ups",
		"server:/backups; rm -rf /",
		"user@@server:/backups",
		"host:/path with space",
	}
	for _, in := range bad {
		if _, _, _, err := ParseOffsiteTarget(in); err == nil {
			t.Fatalf("%q accepted, want rejection", in)
		}
	}
}

func TestCopyOffsiteRejectsBadTarget(t *testing.T) {
	if _, err := CopyOffsite(t.TempDir(), "/nonexistent/file", "not a target"); err == nil {
		t.Fatalf("bad target accepted")
	}
}
