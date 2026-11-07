// Package backup owns shared backup mechanics, including offsite transfer.
// It must not import panel, cli, or maintenance.
package backup

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/crypto"
)

// offsiteTimeout bounds rsync/scp so a hung ssh cannot block the caller
// (backup worker) forever. ssh-level keepalives make dead connections fail
// instead of lingering.
const offsiteTimeout = 5 * time.Minute

// offsiteTargetRe is the accepted shape of an offsite backup target:
// [user@]host:/absolute/path
var offsiteTargetRe = regexp.MustCompile(`^([A-Za-z0-9._-]+@)?([A-Za-z0-9._-]+):(/[\w./-]+)$`)

// ParseOffsiteTarget splits [user@]host:/path and rejects anything else.
func ParseOffsiteTarget(target string) (user, host, path string, err error) {
	trimmed := strings.TrimSpace(target)
	if trimmed == "" {
		return "", "", "", errors.New("offsite backup target is empty")
	}
	match := offsiteTargetRe.FindStringSubmatch(trimmed)
	if match == nil {
		return "", "", "", errors.New(
			"offsite backup target must look like user@server:/path/to/backups (absolute path, no special characters)")
	}
	for _, segment := range strings.Split(match[3], "/") {
		if segment == ".." {
			return "", "", "", errors.New("offsite backup target must not contain '..'")
		}
	}
	if strings.HasPrefix(match[2], "-") || strings.HasPrefix(match[1], "-") {
		return "", "", "", errors.New("offsite backup target must not start with '-'")
	}
	return strings.TrimSuffix(match[1], "@"), match[2], match[3], nil
}

// CopyOffsite pushes one backup file to the offsite target. It returns the
// tool it used ("rsync" or "scp") and the error, if any.
func CopyOffsite(dataDir, sourcePath, target string) (string, error) {
	user, host, dir, err := ParseOffsiteTarget(target)
	if err != nil {
		return "", err
	}
	dest := host
	if user != "" {
		dest = user + "@" + host
	}

	key, keyErr := crypto.GetOrCreateSecretKey(dataDir)
	if keyErr != nil {
		return "", keyErr
	}
	if len(key) != 32 {
		return "", fmt.Errorf("invalid secret key length: %d", len(key))
	}
	encPath := sourcePath + ".enc"
	if err := crypto.EncryptFile(sourcePath, encPath, key); err != nil {
		return "", err
	}
	defer os.Remove(encPath) // #nosec G304 // intentional cleanup

	remote := dest + ":" + strings.TrimSuffix(dir, "/") + "/" + filepath.Base(encPath)

	if _, lookErr := exec.LookPath("rsync"); lookErr == nil {
		ctx, cancel := context.WithTimeout(context.Background(), offsiteTimeout)
		defer cancel()
		cmd := exec.CommandContext(ctx, "rsync", "-a", "-e", "ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3", encPath, remote) // #nosec G204 // arguments validated
		if out, runErr := cmd.CombinedOutput(); runErr != nil {
			return "rsync", fmt.Errorf("rsync failed: %s", strings.TrimSpace(string(out)))
		}
		return "rsync", nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), offsiteTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, "scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", encPath, remote) // #nosec G204 // arguments validated
	if out, runErr := cmd.CombinedOutput(); runErr != nil {
		return "scp", fmt.Errorf("scp failed: %s", strings.TrimSpace(string(out)))
	}
	return "scp", nil
}
