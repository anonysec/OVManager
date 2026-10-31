// Probe helpers: HTTP health, systemd/docker state (cli). Every probe
// used by a golden screen is a package var so tests can inject deterministically.
package cli

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

// Test seams (assigned directly by tests).
var (
	FetchHealth      = fetchHealthImpl
	ServiceState     = serviceStateImpl
	PrimaryIP        = primaryIPImpl
	SystemctlEnabled = systemctlEnabledImpl
	UnitPath         = unitPathImpl
	DiskFreeMB       = diskFreeMBImpl
)

// pinnedTLSConfig mirrors probes._tls_context: chain must match the pinned
// certificate, but the hostname is not checked (the probe dials 127.0.0.1).
func pinnedTLSConfig(cafile string) *tls.Config {
	if cafile == "" {
		return &tls.Config{InsecureSkipVerify: true} // #nosec G402 // probe fallback
	}
	raw, err := os.ReadFile(cafile) // #nosec G304 // triaged intentional
	if err != nil {
		return &tls.Config{InsecureSkipVerify: true} // #nosec G402 // probe fallback
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(raw) {
		return &tls.Config{InsecureSkipVerify: true} // #nosec G402 // probe fallback
	}
	return &tls.Config{
		InsecureSkipVerify:     true, // #nosec G402 // TOFU pinning
		SessionTicketsDisabled: true,
		VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
			for _, der := range rawCerts {
				cert, err := x509.ParseCertificate(der)
				if err != nil {
					continue
				}
				if _, err := cert.Verify(x509.VerifyOptions{Roots: pool}); err == nil {
					return nil
				}
			}
			return &tls.CertificateVerificationError{}
		},
	}
}

func fetchHealthImpl(url string, timeout time.Duration, cafile string) (bool, string) {
	client := &http.Client{Timeout: timeout}
	if strings.HasPrefix(url, "https://") {
		client.Transport = &http.Transport{TLSClientConfig: pinnedTLSConfig(cafile)}
	}
	resp, err := client.Get(url)
	if err != nil {
		return false, "?"
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	var decoded map[string]any
	if json.Unmarshal(body, &decoded) != nil {
		return true, "?"
	}
	version, _ := decoded["version"].(string)
	if version == "" {
		version = "?"
	}
	return true, version
}

func serviceStateImpl(composeFile string) (string, string) {
	if fileExists(composeFile) {
		out, err := exec.Command("docker", "ps", "--format", "{{.Names}}").Output()
		if err != nil {
			return "docker", "unknown"
		}
		if containsWord(string(out), "ovmanager") {
			return "docker", "running"
		}
		return "docker", "stopped"
	}
	out, err := exec.Command("systemctl", "is-active", systemdService).Output()
	if err != nil {
		return "native", "unknown"
	}
	state := strings.TrimSpace(string(out))
	if state == "" {
		state = "unknown"
	}
	return "native", state
}

func primaryIPImpl() string {
	out, err := exec.Command("hostname", "-I").Output()
	if err != nil {
		return "127.0.0.1"
	}
	fields := strings.Fields(string(out))
	if len(fields) > 0 {
		return fields[0]
	}
	return "127.0.0.1"
}

func systemctlEnabledImpl(unit string) bool {
	out, err := exec.Command("systemctl", "is-enabled", unit).Output() // #nosec G204 // triaged intentional
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) == "enabled"
}

func unitPathImpl() string {
	return "/etc/systemd/system/" + systemdService
}

func diskFreeMBImpl(path string) (int64, bool) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, false
	}
	// #nosec // free space cannot overflow on a real filesystem
	return int64(st.Bavail) * int64(st.Bsize) / (1024 * 1024), true
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func containsWord(haystack, word string) bool {
	for _, f := range strings.Fields(haystack) {
		if f == word {
			return true
		}
	}
	return false
}
