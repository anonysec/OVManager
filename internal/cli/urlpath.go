// `ovm urlpath` (cli/urlpath.py): read, set or clear the panel URL prefix. The
// value lives in the settings row, not .env.
package cli

import (
	"strings"

	"github.com/anonysec/OVManager/go/internal/panel"
)

func runURLPathShow(install Install) (string, int) {
	prefix, err := panel.LiveURLPath(install.DataDir)
	if err != nil {
		return block([]string{failedLine("Could not read the live url path: " + err.Error())}), 1
	}
	value := prefix
	if value == "" {
		value = "none — served at /"
	}
	return block(renderRows([][2]string{{"Prefix", value}, {"Source", "database"}})), 0
}

func runURLPathSet(install Install, value string) (string, int) {
	stored, err := panel.SetURLPath(strings.Trim(value, "/"), install.DataDir)
	if err != nil {
		return block([]string{failedLine(err.Error())}), 1
	}
	if stored == "" {
		return block([]string{okLine("url path cleared — the panel is served at /")}), 0
	}
	return block([]string{okLine("url path set"), kv("Prefix", stored)}), 0
}

func runURLPathReset(install Install) (string, int) {
	if _, err := panel.SetURLPath("", install.DataDir); err != nil {
		return block([]string{failedLine("Reset failed: " + err.Error())}), 1
	}
	return block([]string{okLine("panel url prefix cleared — served at /")}), 0
}
