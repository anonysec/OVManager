// `ovm status` (cli): same rows as manager.sh do_status.
package cli

import (
	"os"
	"strconv"
	"time"
)

type statusData struct {
	ok         bool
	installed  bool
	service    string
	mode       string
	health     string
	version    string
	url        string
	installDir string
	dataDir    string
	port       int
	err        string
}

func collectStatus(install Install, service, publicIP string) statusData {
	if info, err := os.Stat(install.InstallDir); err != nil || !info.IsDir() {
		return statusData{err: "Not installed (" + install.InstallDir + " missing)"}
	}
	mode, detected := ServiceState(install.ComposeFile())
	if service == "" {
		service = detected
	}
	reachable, version := FetchHealth(install.HealthURL(), 5*time.Second, install.Cafile())
	health := "unreachable (check logs)"
	if reachable {
		health = "ok"
	}
	if publicIP == "" {
		publicIP = PrimaryIP()
	}
	return statusData{
		ok:         reachable,
		installed:  true,
		mode:       mode,
		service:    service,
		health:     health,
		version:    version,
		url:        install.PublicURL(publicIP, true),
		installDir: install.InstallDir,
		dataDir:    install.DataDir,
		port:       install.Port,
	}
}

func renderStatus(data statusData, showAll bool) string {
	if !data.installed {
		return block([]string{failedLine(data.err)})
	}
	items := [][2]string{
		{"Service", data.service},
		{"Health", data.health},
		{"Version", "v" + data.version},
		{"Open", data.url},
	}
	if showAll {
		items = append(items,
			[2]string{"Mode", data.mode},
			[2]string{"Port", strconv.Itoa(data.port)},
			[2]string{"Data", data.dataDir},
			[2]string{"Install", data.installDir},
		)
	}
	return block(renderRows(items))
}
