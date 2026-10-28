// Package version holds the panel version.
//
// This file is THE single version source: the panel (/health, /api/settings),
// the node agent handshake, the `ovm` CLI and the release/docker workflows all
// read it. install.sh carries a guarded copy (VERSION, must match this const)
// because it runs before any Go toolchain exists; `make version` regenerates
// web/src/version.ts and web/package.json from here before every web build.
package version

// Version is the OVManager release version.
const Version = "2.1.5"
