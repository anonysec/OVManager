// The owner-claim setup key commands.
//
// The panel tells the operator "Run: ovm auth key" when it cannot read the
// setup key, and "ovm auth reset" when the key is lost. Those commands must
// exist, or the panel's own recovery instructions are a dead end — which is
// exactly the case for a container install, where install.sh never ran and no
// key file was ever created.
package cli

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
)

// claimKeyFile is the setup key's name inside the data directory. It matches
// the name install.sh writes and the name internal/auth reads.
const claimKeyFile = "owner-claim.key"

// authCmd groups the owner-claim key commands.
func (a *app) authCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "auth",
		Short: "owner setup key (claim)",
	}
	cmd.AddCommand(a.authKeyCmd(), a.authResetCmd())
	return cmd
}

// authKeyCmd prints the setup key, creating it the first time.
func (a *app) authKeyCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "key",
		Short: "print the owner setup key, creating it if it does not exist",
		RunE: func(_ *cobra.Command, _ []string) error {
			inst := a.install()
			path := filepath.Join(inst.DataDir, claimKeyFile)
			key, created, err := mintClaimKey(path, false)
			if err != nil {
				a.emit(block([]string{failedLine(err.Error())}), 1)
				return nil
			}
			lines := []string{okLine("owner setup key: " + key)}
			if !created {
				lines = append(lines, "The key already existed and was kept; run 'ovm auth reset' for a fresh one.")
			}
			lines = append(lines, "Open the panel and claim it with this key.")
			a.emit(block(lines), 0)
			return nil
		},
	}
}

// authResetCmd replaces the setup key with a fresh one and prints it.
func (a *app) authResetCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "reset",
		Short: "replace the owner setup key with a fresh one and print it",
		RunE: func(_ *cobra.Command, _ []string) error {
			inst := a.install()
			path := filepath.Join(inst.DataDir, claimKeyFile)
			key, _, err := mintClaimKey(path, true)
			if err != nil {
				a.emit(block([]string{failedLine(err.Error())}), 1)
				return nil
			}
			a.emit(block([]string{
				okLine("new owner setup key: " + key),
				"The previous key no longer works. Claim the panel with this one.",
			}), 0)
			return nil
		},
	}
}

// mintClaimKey creates the setup key at path and returns it.
//
// When force is false an existing key is kept: a rerun must never invalidate
// the key a live panel is still holding for its owner claim. When force is
// true the key is replaced (the lost-key case).
func mintClaimKey(path string, force bool) (string, bool, error) {
	if !force {
		if raw, err := os.ReadFile(path); err == nil {
			key := strings.TrimSpace(string(raw))
			if key != "" {
				return key, false, nil
			}
		}
	}
	buf := make([]byte, 16)
	if _, err := rand.Read(buf); err != nil {
		return "", false, fmt.Errorf("could not generate a setup key: %w", err)
	}
	key := hex.EncodeToString(buf)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return "", false, fmt.Errorf("could not create the data directory: %w", err)
	}
	if err := os.WriteFile(path, []byte(key+"\n"), 0o600); err != nil {
		return "", false, fmt.Errorf("could not write the setup key: %w", err)
	}
	// The panel reads this file as its service user, so it must be owned by
	// that user. A non-root operator cannot chown; the file is then left as
	// they wrote it.
	_ = fixTLSOwnership(path, 0o600)
	return key, true, nil
}
