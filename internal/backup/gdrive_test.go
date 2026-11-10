package backup

import "testing"

// A Google Drive target must be rejected when it carries a traversal segment
// or a malformed shape: the panel shells out to rclone with these parts.
func TestParseGoogleDriveTarget(t *testing.T) {
	ok := []struct {
		target, remote, path string
	}{
		{"gdrive:/backups", "gdrive", "/backups"},
		{"gdrive:/ovmanager/backups", "gdrive", "/ovmanager/backups"},
		{"gdrive:mydrive:/backups", "mydrive", "/backups"},
		{"  gdrive:/backups  ", "gdrive", "/backups"},
	}
	for _, c := range ok {
		remote, path, err := ParseGoogleDriveTarget(c.target)
		if err != nil {
			t.Errorf("ParseGoogleDriveTarget(%q): %v", c.target, err)
			continue
		}
		if remote != c.remote || path != c.path {
			t.Errorf("ParseGoogleDriveTarget(%q) = %q %q, want %q %q", c.target, remote, path, c.remote, c.path)
		}
	}
	bad := []string{"", "gdrive:", "gdrive:backups", "gdrive:/../etc", "gdrive::/x", "http://drive"}
	for _, target := range bad {
		if _, _, err := ParseGoogleDriveTarget(target); err == nil {
			t.Errorf("ParseGoogleDriveTarget(%q) accepted an invalid target", target)
		}
	}
}
