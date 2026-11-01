// Service-account helpers shared by the CLI (cli).
package cli

import "os"

// copyFilePerm copies src to dst with the given mode. Kept as a shared helper
// used by update flows.
func copyFilePerm(src, dst string, mode os.FileMode) error {
	raw, err := os.ReadFile(src) // #nosec G304 // triaged intentional
	if err != nil {
		return err
	}
	if err := os.WriteFile(dst, raw, mode); err != nil { // #nosec G703 // copy between trusted paths
		return err
	}
	return os.Chmod(dst, mode)
}
