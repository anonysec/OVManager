// Package webfs carries the panel's built SPA and the subscription page's
// static script inside the binary, so release assets can be bare Go binaries:
// a release install has no web/ tree on disk to read from.
//
// The dist tree is produced by the SPA build and copied here by `make build` /
// the release workflow before `go build`. A committed .gitkeep keeps the embed
// directive valid on a clean checkout (so `go vet` / `go test ./...` compile
// without a prior build); a real dist simply replaces it.
package webfs

import (
	"embed"
	"io/fs"
)

//go:embed all:dist
var distFS embed.FS

// subscription.js is committed here (a verbatim copy of web/templates) and
// refreshed by the same build step: it cannot be read from disk on a release
// install, and internal/panel already embeds its sibling subscription.html the
// same way.
//
//go:embed templates/subscription.js
var subJS string

// Dist is the built SPA rooted at its dist directory, so paths look like
// "index.html" and "assets/<name>.js".
func Dist() fs.FS {
	sub, err := fs.Sub(distFS, "dist")
	if err != nil {
		return distFS
	}
	return sub
}

// SubJS is the subscription page's static script.
func SubJS() string { return subJS }
