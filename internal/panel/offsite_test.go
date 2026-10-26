package panel

import "testing"

// The offsite target is handed to rsync/scp, which run the remote side
// through a shell, so the shape has to be restrictive: a target that walks
// out of the named folder would write somewhere the operator did not name.
func TestParseOffsiteTarget(t *testing.T) {
	cases := []struct {
		target  string
		user    string
		host    string
		path    string
		wantErr bool
	}{
		{target: "backup@server:/backups/panel", user: "backup", host: "server", path: "/backups/panel"},
		{target: "server:/backups/panel", user: "", host: "server", path: "/backups/panel"},
		{target: " backup@server:/backups/panel ", user: "backup", host: "server", path: "/backups/panel"},
		{target: "", wantErr: true},
		{target: "server:/backups/panel; rm -rf /", wantErr: true},
		{target: "server:backups/panel", wantErr: true},
		{target: "server:/backups/../etc", wantErr: true},
		{target: "server:/backups/panel/../../etc", wantErr: true},
		{target: "user@ho st:/backups", wantErr: true},
		{target: "-oProxyCommand=/tmp/x:/backups", wantErr: true},
		{target: "-evil@server:/backups", wantErr: true},
	}
	for _, c := range cases {
		user, host, path, err := ParseOffsiteTarget(c.target)
		if c.wantErr {
			if err == nil {
				t.Errorf("ParseOffsiteTarget(%q) = %q %q %q, want an error", c.target, user, host, path)
			}
			continue
		}
		if err != nil {
			t.Errorf("ParseOffsiteTarget(%q): %v", c.target, err)
			continue
		}
		if user != c.user || host != c.host || path != c.path {
			t.Errorf("ParseOffsiteTarget(%q) = %q %q %q, want %q %q %q",
				c.target, user, host, path, c.user, c.host, c.path)
		}
	}
}
