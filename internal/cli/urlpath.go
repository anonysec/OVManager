// `ovm urlpath` (cli/urlpath.py): read, set or clear the panel URL prefix. The
// value lives in the settings row, not .env.
package cli

import (
	"strings"

	"github.com/anonysec/OVManager/go/internal/maintenance"
)

func runURLPathShow(install Install) (string, int) {
	prefix, err := maintenance.LiveURLPath(install.DataDir)
	if err != nil {
		return block([]string{failedLine("Could not read the live url path: " + err.Error())}), 1
	}
	value := prefix
	if value == "" {
		value = "dashboard (default)"
	}
	return block(renderRows([][2]string{{"Path", value}, {"Source", "database"}})), 0
}

func runURLPathSet(install Install, value string) (string, int) {
	stored, err := maintenance.SetURLPath(strings.Trim(value, "/"), install.DataDir)
	if err != nil {
		return block([]string{failedLine(err.Error())}), 1
	}
	return block([]string{okLine("url path set"), kv("Path", stored)}), 0
}

func runURLPathReset(install Install) (string, int) {
	stored, err := maintenance.SetURLPath("", install.DataDir)
	if err != nil {
		return block([]string{failedLine("Reset failed: " + err.Error())}), 1
	}
	return block([]string{okLine("panel url prefix reset"), kv("Path", stored)}), 0
}
