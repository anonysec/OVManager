// Install layout + .env parsing shared by every CLI command (cli).
package cli

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/anonysec/OVManager/internal/config"
	"github.com/anonysec/OVManager/internal/maintenance"
)

const (
	defaultPort    = 2095
	systemdService = "ovmanager.service"
)

// Install is the resolved install layout. It never touches the network or
// services.
type Install struct {
	InstallDir string
	DataDir    string
	Port       int
	PathPrefix string
	TLSMode    string
	Env        map[string]string
}

var envKeys = []string{
	"Port", "BasePath", "TlsKeyFile", "TlsCertFile", "AcmeHttpPort", "AcmeDirectoryUrl",
	"OwnerUsername", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH",
}

func readEnvFile(path string) map[string]string {
	return config.ReadEnvFile(path)
}

// readInstallEnv backfills the installed .env from the environment where it is
// silent.
func readInstallEnv(path string) map[string]string {
	values := readEnvFile(path)
	for _, key := range envKeys {
		if values[key] == "" {
			if v := os.Getenv(key); v != "" {
				values[key] = v
			}
		}
	}
	return values
}

// DetectInstall resolves the install layout from flags and the environment.
func DetectInstall(installDir, dataDir string) Install {
	if installDir == "" {
		installDir = os.Getenv("OVM_APP_DIR")
	}
	if installDir == "" {
		installDir = "/opt/ovmanager"
	}
	inst := Install{InstallDir: installDir, DataDir: "/var/lib/ovmanager", Port: defaultPort, TLSMode: "none"}
	env := readInstallEnv(filepath.Join(installDir, ".env"))
	inst.Env = env
	if dataDir == "" {
		if v := os.Getenv("DataDir"); v != "" {
			dataDir = v
		}
	}
	if p, err := strconv.Atoi(env["Port"]); err == nil {
		inst.Port = p
	}
	inst.PathPrefix = strings.Trim(env["BasePath"], "/")
	if dataDir != "" {
		inst.DataDir = dataDir
	} else if env["DataDir"] != "" {
		inst.DataDir = env["DataDir"]
	}
	if env["TlsKeyFile"] != "" {
		inst.TLSMode = "self"
	}
	return inst
}

func (i Install) Scheme() string {
	if i.TLSMode == "none" {
		return "http"
	}
	return "https"
}

func (i Install) HealthURL() string {
	return i.Scheme() + "://127.0.0.1:" + strconv.Itoa(i.Port) + "/health"
}

func (i Install) Cafile() string {
	if c := strings.TrimSpace(i.Env["TlsCertFile"]); c != "" {
		return c
	}
	return filepath.Join(i.DataDir, "tls", "fullchain.pem")
}

// LivePathPrefix is the prefix the panel is SERVING, which is not always .env's
// (URLPATH in .env is only the seed). Falls back to the seed when the database
// cannot be read.
func (i Install) LivePathPrefix() string {
	if prefix, err := maintenance.LiveURLPath(i.DataDir); err == nil {
		return prefix
	}
	return i.PathPrefix
}

// PublicURL builds the host URL for this maintenance.
func (i Install) PublicURL(host string, live bool) string {
	if host == "" {
		host = "127.0.0.1"
	}
	base := i.Scheme() + "://" + host + ":" + strconv.Itoa(i.Port)
	prefix := i.PathPrefix
	if live {
		prefix = i.LivePathPrefix()
	}
	if prefix != "" {
		return base + "/" + prefix + "/"
	}
	return base + "/"
}
