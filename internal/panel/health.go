package panel

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"fmt"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	"github.com/anonysec/OVManager/go/internal/version"
)

// check is one row of the /overview checklist.
type check struct {
	ID      string         `json:"id"`
	Status  string         `json:"status"`
	Summary string         `json:"summary"`
	Hint    string         `json:"hint"`
	Detail  map[string]any `json:"detail"`
}

// observed check statuses, keyed by check id: the first observation seeds the
// map silently so a restart never re-pages an old failure.
var checkState = map[string]string{}

const sevenDays = 7 * 24 * 60 * 60

func entry(id, status, summary, hint string, detail map[string]any) check {
	if status == "ok" {
		hint = ""
	}
	if detail == nil {
		detail = map[string]any{}
	}
	return check{ID: id, Status: status, Summary: summary, Hint: hint, Detail: detail}
}

func fmtGB(bytes float64) string { return fmt.Sprintf("%.1f GB", bytes/(1024*1024*1024)) }

func fmtAge(seconds float64) string {
	if seconds < 0 {
		seconds = 0
	}
	if seconds < 60 {
		n := int(seconds)
		if n == 1 {
			return "1 second"
		}
		return strconv.Itoa(n) + " seconds"
	}
	minutes := seconds / 60
	if minutes < 60 {
		n := int(minutes)
		if n == 1 {
			return "1 minute"
		}
		return strconv.Itoa(n) + " minutes"
	}
	hours := minutes / 60
	if hours < 48 {
		n := int(hours)
		if n == 1 {
			return "1 hour"
		}
		return strconv.Itoa(n) + " hours"
	}
	n := int(hours / 24)
	if n == 1 {
		return "1 day"
	}
	return strconv.Itoa(n) + " days"
}

func (h *Handler) healthOverview(w http.ResponseWriter, r *http.Request) {
	checks := make([]map[string]any, 0, 6)
	details := map[string]any{}
	builders := []struct {
		id string
		fn func() check
	}{
		{"panel", h.checkPanel},
		{"database", h.checkDatabase},
		{"nodes", h.checkNodes},
		{"tls", h.checkTLS},
		{"disk", h.checkDisk},
		{"backups", h.checkBackups},
	}
	for _, b := range builders {
		c := func() (out check) {
			defer func() {
				if rec := recover(); rec != nil {
					out = entry(b.id, "error", "The "+b.id+" check could not run.",
						"Try restarting the panel; if the problem continues, check the panel logs. Details: "+
							fmt.Sprint(rec), nil)
				}
			}()
			return b.fn()
		}()
		checks = append(checks, map[string]any{
			"id": c.ID, "status": c.Status, "summary": c.Summary, "hint": c.Hint,
		})
		details[c.ID] = c.Detail
		h.recordCheckTransition(c)
	}
	telemetry.PromoteEvents(h.Svc.DB, func(msg string) bool { return telemetry.SendTelegram(h.Svc.DB, msg) })
	plain(w, map[string]any{"checks": checks, "details": details})
}

func (h *Handler) checkPanel() check {
	uptime := int(time.Since(h.startedAt).Seconds())
	return entry("panel", "ok",
		fmt.Sprintf("Panel version %s has been running for %s on port %d.",
			version.Version, fmtAge(float64(uptime)), serverPort()),
		"",
		map[string]any{
			"version": version.Version, "uptime_seconds": uptime,
			"port": serverPort(), "host": serverHost(),
		})
}

func (h *Handler) checkDatabase() check {
	path := filepath.Join(dataDir(), "ovmanager.db")
	info, err := os.Stat(path)
	if err != nil {
		return entry("database", "error",
			"The database file was not found at "+path+".",
			"Restore a backup from Settings → Backup, or restart the panel so it can recreate the file.",
			map[string]any{"path": path, "size_bytes": nil, "quick_check": nil})
	}
	size := info.Size()
	var raw any
	_ = h.Svc.DB.QueryRow(`PRAGMA quick_check`).Scan(&raw)
	resultText := "ok"
	if raw != nil {
		resultText = fmt.Sprint(raw)
	}
	detail := map[string]any{"path": path, "size_bytes": size, "quick_check": resultText}
	if strings.EqualFold(resultText, "ok") {
		return entry("database", "ok",
			"The database file is "+fmtGB(float64(size))+" and SQLite reports it as ok.", "", detail)
	}
	return entry("database", "error",
		"The database file is "+fmtGB(float64(size))+" but SQLite reported a problem: "+resultText,
		"The database may be damaged. Restore the newest backup from Settings → Backup, then restart the panel.",
		detail)
}

func (h *Handler) checkNodes() check {
	rows, err := h.Svc.DB.Query(`SELECT name FROM nodes ORDER BY id`)
	names := []string{}
	if err == nil {
		for rows.Next() {
			var name string
			if rows.Scan(&name) == nil {
				names = append(names, name)
			}
		}
		rows.Close()
	}
	total := len(names)
	fresh := telemetry.SnapshotFresh()
	online := map[string]bool{}
	if fresh {
		online = telemetry.NodeOnline()
	}
	nodeList := make([]map[string]any, 0, total)
	reachable := 0
	for _, name := range names {
		up := online[name]
		if up {
			reachable++
		}
		nodeList = append(nodeList, map[string]any{
			"name": name, "reachable": up, "latency_ms": nil, "version": nil,
		})
	}
	pollTS := telemetry.LastPollTS()
	detail := map[string]any{
		"total": total, "reachable": reachable, "last_poll_ts": nil, "nodes": nodeList,
	}
	if pollTS != 0 {
		detail["last_poll_ts"] = pollTS
	}
	switch {
	case total == 0:
		return entry("nodes", "warn", "No nodes are configured yet.",
			"Add your first node on the Nodes page so users can connect.", detail)
	case !fresh:
		return entry("nodes", "warn", "The live node data is stale — reachability is unknown.",
			"The live collector has not polled within its idle window. Open the Nodes page to test "+
				"each node, or wait for the next poll.", detail)
	case reachable == 0:
		return entry("nodes", "warn",
			fmt.Sprintf("None of the %d configured nodes answered the latest check.", total),
			"Open the Nodes page and test each node. Make sure the node service is running "+
				"and that its address and API key are correct.", detail)
	case reachable < total:
		return entry("nodes", "warn",
			fmt.Sprintf("%d of %d nodes answered the latest check.", reachable, total),
			"One or more nodes are offline. Open the Nodes page and test the failing node.", detail)
	}
	return entry("nodes", "ok",
		fmt.Sprintf("All %d nodes answered the latest check.", total), "", detail)
}

func (h *Handler) checkTLS() check {
	certFile := strings.TrimSpace(envOrFile("SSL_CERTFILE"))
	keyFile := strings.TrimSpace(envOrFile("SSL_KEYFILE"))
	detail := map[string]any{
		"mode": nil, "cert_file": nil, "key_file": nil,
		"expires_in_days": nil, "expires_at": nil,
	}
	if certFile != "" {
		detail["cert_file"] = certFile
	}
	if keyFile != "" {
		detail["key_file"] = keyFile
	}

	if certFile == "" && keyFile == "" {
		detail["mode"] = "disabled"
		return entry("tls", "warn", "TLS is turned off, so the panel is served over plain HTTP.",
			"Set SSL_CERTFILE and SSL_KEYFILE in the panel settings and restart to serve the panel over HTTPS.",
			detail)
	}
	if certFile == "" || keyFile == "" {
		detail["mode"] = "misconfigured"
		missing := "SSL_CERTFILE"
		if certFile != "" {
			missing = "SSL_KEYFILE"
		}
		return entry("tls", "error", "TLS is only half configured: "+missing+" is missing.",
			"Set both SSL_CERTFILE and SSL_KEYFILE together, or clear both to run the panel without TLS.", detail)
	}
	detail["mode"] = "files"
	for _, p := range []string{certFile, keyFile} {
		if _, err := os.Stat(p); err != nil {
			return entry("tls", "error", "The TLS file was not found: "+p,
				"The configured certificate or key file does not exist. Check the path, or re-run "+
					"the installer to create new certificate files, then restart the panel.", detail)
		}
	}
	cert, err := loadCertificate(certFile)
	if err != nil {
		return entry("tls", "error", "The TLS certificate could not be read: "+err.Error(),
			"The certificate file is not a valid PEM certificate. Replace it with a valid certificate and restart the panel.",
			detail)
	}
	days := daysUntil(cert)
	detail["expires_in_days"] = days
	detail["expires_at"] = cert.NotAfter.UTC().Format(time.RFC3339)
	switch {
	case days < 0:
		return entry("tls", "error",
			fmt.Sprintf("The TLS certificate expired %s ago.", fmtAge(float64(-days)*86400)),
			"Renew the certificate (for example with certbot) and restart the panel.", detail)
	case days <= 14:
		return entry("tls", "warn", fmt.Sprintf("The TLS certificate expires in %d days.", days),
			"Renew the certificate soon so browsers keep trusting the panel.", detail)
	}
	return entry("tls", "ok",
		fmt.Sprintf("TLS is using %s; the certificate expires in %d days.", certFile, days), "", detail)
}

func (h *Handler) checkDisk() check {
	path := dataDir()
	var stat syscall.Statfs_t
	var free, total uint64
	if err := syscall.Statfs(path, &stat); err == nil {
		free = stat.Bavail * uint64(stat.Bsize)
		total = stat.Blocks * uint64(stat.Bsize)
	}
	const gb = 1024 * 1024 * 1024
	percentFree := 0.0
	if total != 0 {
		percentFree = float64(free) / float64(total) * 100
	}
	detail := map[string]any{
		"path": path, "free_bytes": free, "total_bytes": total,
		"free_percent": math.Round(percentFree*10) / 10,
	}
	if percentFree < 10 {
		return entry("disk", "warn",
			fmt.Sprintf("Only %.1f GB of %.1f GB is free on the data disk.",
				float64(free)/gb, float64(total)/gb),
			"Less than 10 percent of the disk is free. Delete old backups or free up space so the panel can keep writing data.",
			detail)
	}
	return entry("disk", "ok",
		fmt.Sprintf("%.1f GB used / %.1f GB total · %.0f%%",
			float64(total-free)/gb, float64(total)/gb, 100-percentFree), "", detail)
}

func (h *Handler) checkBackups() check {
	dir := filepath.Join(dataDir(), "backups")
	detail := map[string]any{"path": dir, "newest": nil, "age_seconds": nil, "size_bytes": nil}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return entry("backups", "warn", "No database backup has been created yet.",
			"Create a backup from Settings → Backup to protect your data.", detail)
	}
	var newest os.FileInfo
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".db" {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		if newest == nil || info.ModTime().After(newest.ModTime()) {
			newest = info
		}
	}
	if newest == nil {
		return entry("backups", "warn", "No database backup has been created yet.",
			"Create a backup from Settings → Backup to protect your data.", detail)
	}
	age := time.Since(newest.ModTime()).Seconds()
	if age < 0 {
		age = 0
	}
	detail["newest"] = newest.Name()
	detail["age_seconds"] = int(age)
	detail["size_bytes"] = newest.Size()
	if age > sevenDays {
		return entry("backups", "warn",
			fmt.Sprintf("The newest backup (%s) is %s old.", newest.Name(), fmtAge(age)),
			"Backups older than a week may be out of date. Create a fresh backup from Settings → Backup.", detail)
	}
	return entry("backups", "ok",
		fmt.Sprintf("The newest backup is %s, created %s ago.", newest.Name(), fmtAge(age)), "", detail)
}

// recordCheckTransition audits one check result — only when its status changed
// (audit.record_event + the node-alerts seeding rule).
func (h *Handler) recordCheckTransition(c check) {
	prev, seen := checkState[c.ID]
	checkState[c.ID] = c.Status
	if !seen || prev == c.Status {
		return
	}
	if c.Status == "ok" {
		telemetry.RecordEvent(h.Svc.DB, "health."+c.ID, "info", c.Summary,
			map[string]any{"target": c.ID})
		return
	}
	severity := "error"
	if c.Status == "warn" {
		severity = "warning"
	}
	telemetry.RecordEvent(h.Svc.DB, "health."+c.ID, severity, c.Summary,
		map[string]any{"event_key": newHexKey(), "status": c.Status, "target": c.ID})
}

func (h *Handler) loginHealth(w http.ResponseWriter, r *http.Request) {
	data := node.LoginHealthSummary(h.Svc.DB, intQuery(r, "hours", 8))
	envelope(w, true, "Login health", data)
}

func (h *Handler) loginDiagnostics(w http.ResponseWriter, r *http.Request) {
	data := node.LoginDiagnostics(r.PathValue("username"), h.Svc.DB, intQuery(r, "hours", 8))
	envelope(w, true, "Login diagnostics", data)
}

func (h *Handler) healthSetup(w http.ResponseWriter, r *http.Request) {
	var nodeCount, activeNodeCount, userCount int
	_ = h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM nodes`).Scan(&nodeCount)
	_ = h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM nodes WHERE status = 1`).Scan(&activeNodeCount)
	_ = h.Svc.DB.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&userCount)
	plain(w, map[string]any{
		"has_node": nodeCount > 0, "has_user": userCount > 0,
		"has_active_node": activeNodeCount > 0,
		"node_count":      nodeCount, "user_count": userCount,
	})
}

// activeCertPath is health.py's _active_cert_path: the panel-managed pair in
// DATA_DIR/tls is only consulted when the declared pair is absent, and the
// declared fallback is SSL_CERTFILE.
func activeCertPath() string {
	legacyKey := filepath.Join(dataDir(), "tls", "privkey.pem")
	legacyCert := filepath.Join(dataDir(), "tls", "fullchain.pem")
	if fileExists(legacyCert) && fileExists(legacyKey) {
		return legacyCert
	}
	certFile := strings.TrimSpace(envOrFile("SSL_CERTFILE"))
	keyFile := strings.TrimSpace(envOrFile("SSL_KEYFILE"))
	if certFile != "" && keyFile != "" && fileExists(certFile) {
		return certFile
	}
	// tls_paths' default is where an install without a declaration keeps its pair.
	if fileExists(sslCertPath()) && fileExists(sslKeyPath()) {
		return sslCertPath()
	}
	return ""
}

func (h *Handler) healthTLS(w http.ResponseWriter, r *http.Request) {
	path := activeCertPath()
	if path == "" {
		plain(w, map[string]any{"issued_by": "unknown", "install_hint": false})
		return
	}
	cert, err := loadCertificate(path)
	if err != nil {
		plain(w, map[string]any{"issued_by": "unknown", "install_hint": false})
		return
	}
	issuedBy := classifyIssuer(cert)
	if issuedBy == "Let's Encrypt" {
		issuedBy = "lets-encrypt"
	}
	switch issuedBy {
	case "self-signed", "lets-encrypt", "custom":
	default:
		issuedBy = "unknown"
	}
	plain(w, map[string]any{
		"issued_by":    issuedBy,
		"install_hint": issuedBy == "lets-encrypt" || issuedBy == "custom",
	})
}

// --- shared certificate helpers ---

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func loadCertificate(path string) (*x509.Certificate, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return parseCertificatePEM(raw)
}

// daysUntil is (not_valid_after_utc - now).days: floored, so an
// expired certificate reports -1 rather than 0.
func daysUntil(cert *x509.Certificate) int {
	return int(math.Floor(time.Until(cert.NotAfter).Hours() / 24))
}

func classifyIssuer(cert *x509.Certificate) string {
	issuer := cert.Issuer.String()
	if strings.Contains(issuer, "Let's Encrypt") {
		return "Let's Encrypt"
	}
	if issuer == cert.Subject.String() {
		return "self-signed"
	}
	return "custom"
}

// fingerprintSHA256 renders cert.fingerprint(SHA256).hex(":").upper().
func fingerprintSHA256(cert *x509.Certificate) string {
	sum := sha256.Sum256(cert.Raw)
	out := make([]string, len(sum))
	for i, b := range sum {
		out[i] = strings.ToUpper(hex.EncodeToString([]byte{b}))
	}
	return strings.Join(out, ":")
}

// newHexKey is uuid4().hex for audit event keys.
func newHexKey() string {
	buf := make([]byte, 16)
	if _, err := cryptoRead(buf); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 16)
	}
	return hex.EncodeToString(buf)
}
