// Shared small formatters (cli).
package cli

import (
	"fmt"
	"os"
	"os/user"
	"strconv"
	"time"
)

func humanSize(size int64) string {
	switch {
	case size < 1024:
		return fmt.Sprintf("%d B", size)
	case size < 1024*1024:
		return fmt.Sprintf("%.1f KB", float64(size)/1024)
	default:
		return fmt.Sprintf("%.1f MB", float64(size)/(1024*1024))
	}
}

// timeFormat mirrors datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M").
func timeFormat(epoch float64) string {
	return time.Unix(int64(epoch), 0).Format("2006-01-02 15:04")
}

// fixTLSOwnership makes a freshly written TLS file readable by the panel
// process. When running as root it chowns the file to the unit file's
// service account (and its group) and applies mode; non-root operators cannot
// chown, so the call is a no-op there. Errors are returned only when a chown
// or chmod that was actually attempted fails.
func fixTLSOwnership(path string, mode os.FileMode) error {
	if os.Geteuid() != 0 {
		return nil
	}
	account := unitUser()
	if account == "" {
		return nil
	}
	u, err := user.Lookup(account)
	if err != nil {
		return nil
	}
	uid, err := strconv.Atoi(u.Uid)
	if err != nil {
		return nil
	}
	gid := groupGID(account)
	if gid < 0 {
		return nil
	}
	if err := os.Chown(path, uid, gid); err != nil {
		return err
	}
	return os.Chmod(path, mode)
}
