// In-panel DB export/import (plan Task 5) — the /api/db/* surface.
//
// The full export/restore machinery already lives in maintenance.go:
// backupDownload streams the newest stored snapshot, and backupRestore walks
// the atomic staging restore (stage → safety backup → activate → verify →
// rollback). Rather than duplicating either, these routes are thin owner-gated
// aliases over those handlers, so the plan's stable db/* contract exists
// without a second restore implementation.
package panel

import "net/http"

// MountDBOps registers the Task 5 db routes. owner is the auth service's
// RequireOwner gate, passed in by Mount.
func (h *Handler) MountDBOps(mux *http.ServeMux, owner func(http.HandlerFunc) http.HandlerFunc) {
	mux.HandleFunc("GET /db/backup", owner(h.backupDownload))
	mux.HandleFunc("POST /db/restore", owner(h.backupRestore))
}
