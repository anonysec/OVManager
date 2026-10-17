// Shared small formatters (cli/restore.py _human_size, cli/status.py).
package cli

import (
	"fmt"
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
