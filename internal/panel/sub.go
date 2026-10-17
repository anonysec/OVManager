package panel

import (
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"html"
	"html/template"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/go/internal/node"
	"github.com/anonysec/OVManager/go/internal/telemetry"
	"github.com/anonysec/OVManager/go/internal/webfs"
)

// Subscription page (backend/routers/sub.py). The template is the Jinja source
// from frontend/templates/subscription.html converted to html/template syntax
// (backend/ is going away, so the Go copy is the live one).
//
//go:embed subscription.html
var subscriptionTemplate string

type subLink struct {
	Node string
	Link string
}

type subView struct {
	Name                   string
	ExpiryDate             string
	DaysLeft               *int
	UsedPct                *int
	Total                  *int64
	Used                   int64
	IsActive               bool
	Links                  []subLink
	SubProfileTitle        string
	SubSupportURL          string
	SubAnnounce            string
	SubUpdateIntervalHours int
}

// fmtBytes is the Jinja macro fmt_bytes: a human-readable byte size.
func fmtBytes(b int64) string {
	n := float64(b)
	switch {
	case n >= 1099511627776:
		return strconv.FormatFloat(n/1099511627776, 'f', 2, 64) + " TB"
	case n >= 1073741824:
		return strconv.FormatFloat(n/1073741824, 'f', 2, 64) + " GB"
	case n >= 1048576:
		return strconv.FormatFloat(n/1048576, 'f', 1, 64) + " MB"
	case n >= 1024:
		return strconv.FormatFloat(n/1024, 'f', 0, 64) + " KB"
	}
	return strconv.FormatFloat(n, 'f', 0, 64) + " B"
}

var subFuncs = template.FuncMap{
	"fmtBytes": fmtBytes,
	// totalText is `{% if total %}{{ fmt_bytes(total) }}{% else %}∞{% endif %}`.
	"totalText": func(v *int64) string {
		if v == nil || *v == 0 {
			return "∞"
		}
		return fmtBytes(*v)
	},
	"daysText": func(v *int) string {
		if v == nil {
			return "∞"
		}
		return strconv.Itoa(*v)
	},
	"pctText": func(v *int) string {
		if v == nil {
			return "∞"
		}
		return strconv.Itoa(*v) + "%"
	},
	"pctWidth": func(v *int) string {
		if v == nil {
			return "100"
		}
		return strconv.Itoa(*v)
	},
	"le": func(v *int, n int) bool { return v != nil && *v <= n },
}

var subTmpl = template.Must(template.New("subscription").Funcs(subFuncs).Parse(subscriptionTemplate))

// Subscription rate limiting (sub.py: 30 hits / 60s per IP, capped buckets).
const (
	subMax        = 30
	subWindow     = 60.0
	subMaxBuckets = 10000
)

var (
	subMu          sync.Mutex
	subAttempts    = map[string][]float64{}
	subLastCleanup float64
)

func (h *Handler) subRateLimited(r *http.Request) bool {
	key := sha16(h.clientIP(r))
	now := float64(time.Now().UnixNano()) / 1e9
	subMu.Lock()
	defer subMu.Unlock()
	subEnforceCap()
	if now-subLastCleanup >= subWindow {
		subLastCleanup = now
		for k, hits := range subAttempts {
			if len(hits) == 0 || now-hits[len(hits)-1] >= subWindow {
				delete(subAttempts, k)
			}
		}
	}
	hits := []float64{}
	for _, t := range subAttempts[key] {
		if now-t < subWindow {
			hits = append(hits, t)
		}
	}
	if len(hits) >= subMax {
		subAttempts[key] = hits
		return true
	}
	subAttempts[key] = append(hits, now)
	return false
}

func subEnforceCap() {
	overflow := len(subAttempts) - subMaxBuckets
	if overflow <= 0 {
		return
	}
	type bucket struct {
		key string
		ts  float64
	}
	buckets := make([]bucket, 0, len(subAttempts))
	for k, hits := range subAttempts {
		ts := 0.0
		if len(hits) > 0 {
			ts = hits[len(hits)-1]
		}
		buckets = append(buckets, bucket{k, ts})
	}
	for i := 1; i < len(buckets); i++ {
		for j := i; j > 0 && buckets[j].ts < buckets[j-1].ts; j-- {
			buckets[j], buckets[j-1] = buckets[j-1], buckets[j]
		}
	}
	for i := 0; i < overflow && i < len(buckets); i++ {
		delete(subAttempts, buckets[i].key)
	}
}

func sha16(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])[:16]
}

func (h *Handler) subStaticJS(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/javascript")
	w.Header().Set("Cache-Control", "public, max-age=3600")
	// Disk override for dev; a release install has no web/ tree, so the copy
	// embedded in the binary is the fallback (and the norm there).
	path := filepath.Join(appDir(), "web", "templates", "subscription.js")
	if fileExists(path) {
		http.ServeFile(w, r, path)
		return
	}
	_, _ = io.WriteString(w, webfs.SubJS())
}

func (h *Handler) subPage(w http.ResponseWriter, r *http.Request) {
	if h.subRateLimited(r) {
		writeSubError(w, 429, "Too Many Requests", "Please try again in a minute.")
		return
	}
	uuid := r.PathValue("uuid")
	user, ok := h.subUser(w, uuid, r)
	if !ok {
		return
	}
	nodes := h.activeNodes()

	type nodeEntry struct {
		name string
		ok   bool
	}
	online := map[string]bool{}
	if telemetry.SnapshotFresh() {
		online = telemetry.NodeOnline()
	}
	links := []subLink{}
	for _, n := range nodes {
		if online[n.Name] {
			links = append(links, subLink{
				Node: n.Name,
				Link: baseURL(r) + subscriptionPath() + "/download/" + uuid + "/" + n.Name,
			})
		}
	}

	s := h.settings()
	interval := s.intOr("sub_update_interval_hours", 12)
	view := subView{
		Name:                   user.name,
		ExpiryDate:             fmtDate(user.expiryDate),
		DaysLeft:               user.daysLeft,
		UsedPct:                user.usedPct,
		Total:                  user.total,
		Used:                   user.used,
		IsActive:               user.isActive,
		Links:                  links,
		SubProfileTitle:        strings.TrimSpace(s.strOr("sub_profile_title")),
		SubSupportURL:          strings.TrimSpace(s.strOr("sub_support_url")),
		SubAnnounce:            strings.TrimSpace(s.strOr("sub_announce")),
		SubUpdateIntervalHours: interval,
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = subTmpl.Execute(w, view)
}

func (h *Handler) subDownload(w http.ResponseWriter, r *http.Request) {
	if h.subRateLimited(r) {
		writeSubError(w, 429, "Too Many Requests", "Please try again in a minute.")
		return
	}
	user, ok := h.subUser(w, r.PathValue("uuid"), r)
	if !ok {
		return
	}
	nodeName := r.PathValue("node_name")
	nodeObj := h.nodeByName(nodeName)
	if nodeObj == nil {
		writeSubError(w, 404, "Not Found", "The requested node was not found.")
		return
	}
	body := node.DownloadOVPNClient(user.id, nodeObj.ID, h.Svc.DB)
	if len(body) == 0 {
		writeSubError(w, 404, "Not Found", "The configuration file could not be generated.")
		return
	}
	w.Header().Set("Content-Type", "application/x-openvpn-profile")
	w.Header().Set("Content-Disposition", `attachment; filename="`+user.name+".ovpn"+`"`)
	_, _ = w.Write(body)
}

// subUser is the shared lookup + gating for both subscription routes. It
// writes the error page and returns false when the user may not proceed.
type subUserRow struct {
	id         int64
	name       string
	total      *int64
	used       int64
	isActive   bool
	expiryDate string
	daysLeft   *int
	usedPct    *int
}

func (h *Handler) subUser(w http.ResponseWriter, uuid string, r *http.Request) (subUserRow, bool) {
	var row subUserRow
	var total sql.NullInt64
	var used sql.NullInt64
	var expiry sql.NullString
	var active sql.NullInt64
	err := h.Svc.DB.QueryRow(
		`SELECT id, name, total, used, expiry_date, is_active FROM users WHERE uuid = ?`, uuid,
	).Scan(&row.id, &row.name, &total, &used, &expiry, &active)
	if err == sql.ErrNoRows {
		writeSubError(w, 404, "Not Found", "This subscription link is invalid or the user no longer exists.")
		return row, false
	}
	if err != nil {
		writeSubError(w, 404, "Not Found", "This subscription link is invalid or the user no longer exists.")
		return row, false
	}
	if total.Valid {
		v := total.Int64
		row.total = &v
	}
	row.used = used.Int64
	row.isActive = active.Int64 != 0
	row.expiryDate = expiry.String
	row.daysLeft = daysLeft(expiry)
	row.usedPct = usedPct(row.used, row.total)

	today := time.Now().Format("2006-01-02")
	switch {
	case expiry.Valid && expiry.String != "" && expiry.String[:min10(len(expiry.String))] < today:
		writeSubError(w, 403, "Expired", "This subscription has expired. Contact your administrator to extend it.")
		return row, false
	case !row.isActive:
		writeSubError(w, 403, "Account Disabled", "This user account is currently disabled. Contact your administrator to reactivate it.")
		return row, false
	case row.total != nil && row.used >= *row.total:
		writeSubError(w, 403, "Traffic Limit Reached", "This user has used all allocated traffic. Contact your administrator to increase the limit.")
		return row, false
	}
	return row, true
}

func min10(n int) int {
	if n > 10 {
		return 10
	}
	return n
}

// daysLeft is sub._days_left: days until expiry, nil when unset.
func daysLeft(expiry sql.NullString) *int {
	if !expiry.Valid || expiry.String == "" {
		return nil
	}
	raw := expiry.String[:min10(len(expiry.String))]
	parsed, err := time.Parse("2006-01-02", raw)
	if err != nil {
		return nil
	}
	today := time.Now()
	today = time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	days := int(parsed.Sub(today).Hours() / 24)
	return &days
}

// usedPct is sub._used_pct.
func usedPct(used int64, total *int64) *int {
	if total == nil {
		return nil
	}
	if *total <= 0 {
		v := 0
		if used > 0 {
			v = 100
		}
		return &v
	}
	v := int(float64(used) / float64(*total) * 100)
	// Python's round() is banker's rounding; traffic percentages never land on
	// an exact .5 in practice, and the UI only prints the integer.
	if v > 100 {
		v = 100
	}
	if v < 0 {
		v = 0
	}
	return &v
}

// fmtDate is sub._fmt_date: YYYY-MM-DD, or an em dash when unset.
func fmtDate(value string) string {
	if value == "" {
		return "—"
	}
	if len(value) >= 10 {
		return value[:10]
	}
	return value
}

func (h *Handler) activeNodes() []*node.Node {
	rows, err := h.Svc.DB.Query(
		`SELECT id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca
		 FROM nodes WHERE status = 1 ORDER BY id`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	out := []*node.Node{}
	for rows.Next() {
		out = append(out, scanNodeRow(rows))
	}
	return out
}

func (h *Handler) nodeByName(name string) *node.Node {
	rows, err := h.Svc.DB.Query(
		`SELECT id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca
		 FROM nodes WHERE name = ?`, name)
	if err != nil {
		return nil
	}
	defer rows.Close()
	if !rows.Next() {
		return nil
	}
	return scanNodeRow(rows)
}

type scanner interface{ Scan(...any) error }

func scanNodeRow(row scanner) *node.Node {
	n := &node.Node{}
	var tunnel, key, country sql.NullString
	var ovpnPort, port, status sql.NullInt64
	var serverCA sql.NullString
	var protocol sql.NullString
	if err := row.Scan(&n.ID, &n.Name, &n.Address, &tunnel, &protocol, &ovpnPort, &port, &key, &status, &serverCA); err != nil {
		return nil
	}
	n.TunnelAddress = tunnel.String
	n.Protocol = protocol.String
	n.OVPNPort = int(ovpnPort.Int64)
	n.Port = int(port.Int64)
	n.Key = key.String
	n.Status = status.Int64 != 0
	n.ServerCA = serverCA
	n.CountryCode = country
	return n
}

// writeSubError renders sub_error_page verbatim.
func writeSubError(w http.ResponseWriter, status int, title, message string) {
	safeTitle := html.EscapeString(title)
	safeMessage := html.EscapeString(message)
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(subErrorPage(safeTitle, safeMessage)))
}

func subErrorPage(safeTitle, safeMessage string) string {
	return `<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>` + safeTitle + `</title>
<style>
  :root { --bg:#0f172a; --surface:#1e293b; --text:#f8fafc; --muted:#94a3b8; --border:#334155; --orange:#ea7e20; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:'Plus Jakarta Sans',system-ui,sans-serif; background:var(--bg); color:var(--text);
         min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px; }
  .card { width:100%; max-width:420px; background:var(--surface); border:1px solid var(--border);
          border-radius:24px; padding:32px 28px; text-align:center; box-shadow:0 20px 25px -5px rgba(0,0,0,.3); }
  .badge { display:inline-flex; align-items:center; gap:8px; padding:6px 16px; border-radius:50px;
           background:rgba(239,68,68,.12); color:#ef4444; border:1px solid rgba(239,68,68,.25);
           font-weight:600; font-size:.85rem; margin-bottom:16px; }
  h2 { font-size:1.3rem; margin-bottom:10px; }
  p { color:var(--muted); font-size:.92rem; line-height:1.5; }
  .ovpn { color:var(--orange); font-weight:700; }
</style>
</head>
<body>
  <div class="card">
    <div class="badge">● ` + safeTitle + `</div>
    <h2>` + safeMessage + `</h2>
    <p>This is an <span class="ovpn">OpenVPN</span> panel. To connect, download the <b>.ovpn</b> config
       from your provider's dashboard (per-node <b>Get Config</b>) and import it into an OpenVPN client.
       OpenVPN does not use HTTP subscription links.</p>
  </div>
</body>
</html>`
}

var _ = os.Getenv
