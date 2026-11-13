// Package version holds the panel version.
//
// This file is THE single version source: the panel (/health, /api/settings),
// the node agent handshake, the `ovmanager` CLI and the release workflows all
// read it. install.sh carries a guarded copy (VERSION, must match this const)
// because it runs before any Go toolchain exists; `make version` regenerates
// web/src/version.ts and web/package.json from here before every web build.
package version

import (
	"strconv"
	"strings"
)

// Version is the OVManager release version.
var Version = "2.0.9"

// IsLegacyPreReset reports whether tag or version string belongs to the retired
// 2.1.0–2.4.6 pre-reset line.
func IsLegacyPreReset(v string) bool {
	v = strings.TrimPrefix(strings.TrimSpace(v), "v")
	parts := strings.Split(v, ".")
	if len(parts) >= 2 && parts[0] == "2" {
		if minor, err := strconv.Atoi(parts[1]); err == nil && minor >= 1 && minor <= 4 {
			return true
		}
	}
	return false
}
