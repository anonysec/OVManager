// Node CRUD + management endpoints (backend/node/management.py and
// backend/routers/node.py).
package node

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"crypto/x509"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"net"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/audit"
	"github.com/anonysec/OVManager/go/internal/auth"
	"github.com/anonysec/OVManager/go/internal/version"
)

// --- settings / crud helpers ---

// PanelIDFor resolves this panel's X-Panel-ID from settings, or "".
func PanelIDFor(db *sql.DB) string {
	if db == nil {
		return ""
	}
	var pid sql.NullString
	if err := db.QueryRow(`SELECT panel_id FROM settings LIMIT 1`).Scan(&pid); err != nil {
		return ""
	}
	return pid.String
}

func panelDomainFor(db *sql.DB) string {
	var d sql.NullString
	if err := db.QueryRow(`SELECT panel_domain FROM settings LIMIT 1`).Scan(&d); err != nil {
		return ""
	}
	return strings.TrimSpace(d.String)
}

func getKV(db *sql.DB, key string) string {
	var v sql.NullString
	if err := db.QueryRow(`SELECT value FROM settings_kv WHERE key = ?`, key).Scan(&v); err != nil {
		return ""
	}
	return v.String
}

const nodeCols = `id, name, address, COALESCE(tunnel_address,''), protocol, ovpn_port, port,
	COALESCE(key,''), status, server_ca, country_code, latitude, longitude, COALESCE(extra_ports,'')`

func scanNode(row interface{ Scan(...any) error }) (*Node, error) {
	n := &Node{}
	err := row.Scan(&n.ID, &n.Name, &n.Address, &n.TunnelAddress, &n.Protocol, &n.OVPNPort,
		&n.Port, &n.Key, &n.Status, &n.ServerCA, &n.CountryCode, &n.Latitude, &n.Longitude, &n.ExtraPorts)
	if err != nil {
		return nil, err
	}
	return n, nil
}

// GetNodeByID loads one node row, or nil.
func GetNodeByID(db *sql.DB, id int64) *Node {
	n, err := scanNode(db.QueryRow(`SELECT `+nodeCols+` FROM nodes WHERE id = ?`, id))
	if err != nil {
		return nil
	}
	return n
}

func getNodeByName(db *sql.DB, name string) *Node {
	n, err := scanNode(db.QueryRow(`SELECT `+nodeCols+` FROM nodes WHERE name = ?`, name))
	if err != nil {
		return nil
	}
	return n
}

func getAllNodes(db *sql.DB) []*Node {
	rows, err := db.Query(`SELECT ` + nodeCols + ` FROM nodes`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	return collectNodes(rows)
}

func getActiveNodes(db *sql.DB) []*Node {
	nodes, _ := getActiveNodesWithErr(db)
	return nodes
}

func getActiveNodesWithErr(db *sql.DB) ([]*Node, error) {
	rows, err := db.Query(`SELECT ` + nodeCols + ` FROM nodes WHERE status = 1`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return collectNodes(rows), nil
}

func collectNodes(rows *sql.Rows) []*Node {
	var out []*Node
	for rows.Next() {
		n, err := scanNode(rows)
		if err != nil {
			return out
		}
		out = append(out, n)
	}
	return out
}

// --- version compatibility (management.node_version_compat) ---

var versionRe = regexp.MustCompile(`^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?`)

func versionParts(v any) ([]int, bool) {
	s, ok := v.(string)
	if !ok || s == "" {
		return nil, false
	}
	m := versionRe.FindStringSubmatch(s)
	if m == nil {
		return nil, false
	}
	parts := make([]int, 3)
	for i := 0; i < 3; i++ {
		if m[i+1] != "" {
			parts[i], _ = strconv.Atoi(m[i+1])
		}
	}
	return parts, true
}

// minNodeMajor is the lowest node major version this panel supports.
const minNodeMajor = 1

// nodeVersionCompat judges a node agent version against this panel.
func nodeVersionCompat(agentVersion any) map[string]any {
	agent, okA := versionParts(agentVersion)
	panel, okP := versionParts(version.Version)
	out := map[string]any{"agent_version": agentVersion, "panel_version": version.Version}
	if !okA || !okP {
		out["verdict"] = "unknown"
		return out
	}
	cmp := compareParts(agent, panel)
	switch {
	case agent[0] < minNodeMajor:
		out["verdict"] = "incompatible"
	case cmp > 0:
		out["verdict"] = "node-newer"
	default:
		out["verdict"] = "compatible"
	}
	return out
}

func compareParts(a, b []int) int {
	for i := 0; i < 3; i++ {
		if a[i] != b[i] {
			if a[i] > b[i] {
				return 1
			}
			return -1
		}
	}
	return 0
}

// --- cert pin payload (management._cert_pin_payload) ---

func certPinPayload(n *Node) map[string]any {
	out := map[string]any{"pinned": false, "fingerprint": nil, "expiry": nil, "issuer": nil, "match": nil}
	pinned := n.ServerCA.String
	if !isPEM(pinned) {
		return out
	}
	block, _ := pem.Decode([]byte(pinned))
	if block == nil {
		return out
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return out
	}
	sum := sha256.Sum256(cert.Raw)
	hexParts := make([]string, len(sum))
	for i, b := range sum {
		hexParts[i] = strings.ToUpper(hex.EncodeToString([]byte{b}))
	}
	out["pinned"] = true
	out["fingerprint"] = strings.Join(hexParts, ":")
	out["expiry"] = cert.NotAfter.UTC().Format(time.RFC3339)
	out["issuer"] = cert.Issuer.String()
	return out
}

// --- list / status ---

func listNodes(db *sql.DB) []map[string]any {
	nodes := getAllNodes(db)
	out := make([]map[string]any, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, map[string]any{
			"id":             n.ID,
			"name":           n.Name,
			"address":        n.Address,
			"tunnel_address": n.TunnelAddress,
			"protocol":       n.Protocol,
			"ovpn_port":      n.OVPNPort,
			"port":           n.Port,
			"status":         n.Status,
			"country_code":   n.CountryCode.String,
			"latitude":       nullFloat(n.Latitude),
			"longitude":      nullFloat(n.Longitude),
			"extra_ports":    n.ExtraPorts,
		})
	}
	return out
}

func nullFloat(v sql.NullFloat64) any {
	if !v.Valid {
		return nil
	}
	return v.Float64
}

// GetNodeStatus builds the node status payload, or nil for an unknown id.
func GetNodeStatus(db *sql.DB, nodeID int64) map[string]any {
	n := GetNodeByID(db, nodeID)
	if n == nil {
		return nil
	}
	pid := PanelIDFor(db)
	started := time.Now()

	type infoRes struct {
		info     map[string]any
		sessions map[string]any
		verified *bool
		mode     string
	}
	ch := make(chan infoRes, 1)
	go func() {
		infoC := NodeClient(n, pid)
		sessC := NodeClient(n, pid)
		infoCh := make(chan map[string]any, 1)
		// ponytail: sessions use LongTimeout like management.get_node_status.
		sessCh := make(chan map[string]any, 1)
		go func() { infoCh <- infoC.GetNodeInfo() }()
		go func() { sessCh <- sessC.GetSessions("", 8, 0) }()
		info := <-infoCh
		sessions := <-sessCh
		mode := infoC.TLSMode()
		if infoC.TLSVerified() == nil {
			mode = sessC.TLSMode()
		}
		verified := infoC.TLSVerified()
		if verified == nil {
			verified = sessC.TLSVerified()
		}
		ch <- infoRes{info: info, sessions: sessions, verified: verified, mode: mode}
	}()
	res := <-ch

	certPin := certPinPayload(n)
	if certPin["pinned"] == true {
		switch res.mode {
		case "verified":
			certPin["match"] = true
		case "unverified-self-signed":
			certPin["match"] = false
		}
	}

	var tlsVerified any
	if res.verified != nil {
		tlsVerified = *res.verified
	}
	latency := float64(time.Since(started).Microseconds()) / 1000.0
	latency = float64(int(latency*10+0.5)) / 10

	return map[string]any{
		"node": map[string]any{
			"id":          n.ID,
			"name":        n.Name,
			"address":     n.Address,
			"status":      n.Status,
			"extra_ports": n.ExtraPorts,
		},
		"node_info":           orEmpty(res.info),
		"version_compat":      nodeVersionCompat(res.info["version"]),
		"session_diagnostics": orEmpty(res.sessions),
		"latency_ms":          latency,
		"reachable":           len(res.info) > 0,
		"tls_verified":        tlsVerified,
		"tls_mode":            res.mode,
		"cert_pin":            certPin,
	}
}

func orEmpty(m map[string]any) map[string]any {
	if m == nil {
		return map[string]any{}
	}
	return m
}

// --- handlers request bodies ---

type nodeCreate struct {
	Name          string  `json:"name"`
	Address       string  `json:"address"`
	TunnelAddress *string `json:"tunnel_address"`
	Protocol      string  `json:"protocol"`
	OVPNPort      int     `json:"ovpn_port"`
	Port          int     `json:"port"`
	Key           *string `json:"key"`
	Cert          *string `json:"cert"`
	Status        *bool   `json:"status"`
	CountryCode   *string `json:"country_code"`
}

func (r nodeCreate) key() string {
	if r.Key == nil {
		return ""
	}
	return *r.Key
}

func (r nodeCreate) tunnel() string {
	if r.TunnelAddress == nil {
		return ""
	}
	return *r.TunnelAddress
}

func (r nodeCreate) protocol() string {
	if r.Protocol == "" {
		return "tcp"
	}
	return r.Protocol
}

func (r nodeCreate) ovpnPort() int {
	if r.OVPNPort == 0 {
		return 1194
	}
	return r.OVPNPort
}

func (r nodeCreate) port() int {
	if r.Port == 0 {
		return 2083
	}
	return r.Port
}

func (r nodeCreate) status() bool {
	if r.Status == nil {
		return true
	}
	return *r.Status
}

// --- management operations ---

// AddNodeHandler registers a new node. A node-side 409 surfaces the node's own
// message. geolocation is skipped (backend/utils/geolocation.py is out of this
// phase): country_code comes from the manual override only.
func AddNodeHandler(req nodeCreate, db *sql.DB) (bool, string) {
	serverCA := ""
	if req.Cert != nil {
		serverCA = *req.Cert
	}
	nr, err := NewClient(req.Address, req.port(), req.key(), serverCA, PanelIDFor(db), 0)
	if err != nil {
		return false, err.Error()
	}
	if !nr.CheckNode() {
		return false, nr.ConflictMsg()
	}
	configured := nr.UpdateConfig(UpdateConfigParams{
		TunnelAddress: req.tunnel(), Protocol: req.protocol(), OVPNPort: req.ovpnPort(),
	})
	if configured != true {
		return false, nr.ConflictMsg()
	}
	id, err := createNode(db, req, serverCA)
	if err != nil {
		return false, err.Error()
	}
	_ = id
	audit.Record(db, "admin", "node.create", "info", fmt.Sprintf("Node added: %s (%s:%d)", req.Name, req.Address, req.port()), map[string]any{"target": req.Name, "address": req.Address, "port": req.port()})
	return true, "Node added successfully"
}

// UpdateNodeHandler persists metadata first, then applies settings to the node.
func UpdateNodeHandler(nodeID int64, req nodeCreate, db *sql.DB) (bool, string) {
	existing := GetNodeByID(db, nodeID)
	if existing == nil {
		return false, "Node not found"
	}
	cert := ""
	if req.Cert != nil {
		cert = *req.Cert
	}
	structural := req.tunnel() != existing.TunnelAddress ||
		req.protocol() != existing.Protocol ||
		req.ovpnPort() != existing.OVPNPort ||
		(cert != "" && cert != existing.ServerCA.String)

	apiKey := req.key()
	if apiKey == "" {
		apiKey = existing.Key
	}
	serverCA := cert
	if serverCA == "" {
		serverCA = existing.ServerCA.String
	}
	if err := updateNode(db, nodeID, req, cert, apiKey); err != nil {
		return false, err.Error()
	}
	if structural {
		// ponytail: restart-debounce worker (operations/restart_debounce.py) is
		// out of this phase; the flag is not queued.
		_ = structural
	}
	nr, err := NewClient(req.Address, req.port(), apiKey, serverCA, PanelIDFor(db), 0)
	if err != nil {
		return false, err.Error()
	}
	if !nr.CheckNode() {
		if msg := nr.ConflictMsg(); msg != "" {
			return false, msg
		}
		return false, "Node unreachable — the panel saved the record but could not apply the settings. Configure after registration."
	}
	if nr.UpdateConfig(UpdateConfigParams{TunnelAddress: req.tunnel(), Protocol: req.protocol(), OVPNPort: req.ovpnPort()}) != true {
		return true, "Node updated, but the new VPN settings could not be applied on the node."
	}
	return true, "Node updated successfully"
}

// DeleteNodeHandler deletes the node row and drops its connection.
// It also cleans up the node's traffic baselines and push hashes from all users.
func DeleteNodeHandler(nodeID int64, db *sql.DB) bool {
	res, err := db.Exec(`DELETE FROM nodes WHERE id = ?`, nodeID)
	if err != nil {
		return false
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return false
	}
	Forget(nodeID)

	// Clean up node's traffic baselines and push hashes from all users.
	nodeIDStr := strconv.FormatInt(nodeID, 10)
	jsonPath1 := "$.\"" + nodeIDStr + "\""
	jsonPath2 := "$.push_hash.\"" + nodeIDStr + "\""
	_, _ = db.Exec(
		"UPDATE users SET node_usage = json_remove(node_usage, ?) WHERE json_type(node_usage, ?) IS NOT NULL",
		jsonPath1, jsonPath1)
	_, _ = db.Exec(
		"UPDATE users SET node_usage = json_remove(node_usage, ?) WHERE json_type(node_usage, ?) IS NOT NULL",
		jsonPath2, jsonPath2)

	audit.Record(db, "admin", "node.delete", "warning", fmt.Sprintf("Node deleted (ID: %d)", nodeID), map[string]any{"node_id": nodeID})

	return true
}

func createNode(db *sql.DB, req nodeCreate, serverCA string) (int64, error) {
	manual := ""
	if req.CountryCode != nil {
		manual = strings.ToUpper(strings.TrimSpace(*req.CountryCode))
	}
	var cc any
	var lat any
	var lon any
	if manual != "" {
		cc = manual
	} else if code, lLat, lLon, ok := Geolocate(req.Address); ok {
		cc = code
		lat = lLat
		lon = lLon
	}
	res, err := db.Exec(
		`INSERT INTO nodes (name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca, country_code, latitude, longitude)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		req.Name, req.Address, req.tunnel(), req.protocol(), req.ovpnPort(), req.port(),
		req.key(), req.status(), nullIfEmpty(serverCA), cc, lat, lon,
	)
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

func updateNode(db *sql.DB, id int64, req nodeCreate, cert, apiKey string) error {
	manual := ""
	if req.CountryCode != nil {
		manual = strings.ToUpper(strings.TrimSpace(*req.CountryCode))
	}
	set := `name=?, address=?, tunnel_address=?, protocol=?, ovpn_port=?, port=?, status=?, key=?`
	args := []any{req.Name, req.Address, req.tunnel(), req.protocol(), req.ovpnPort(), req.port(), req.status(), apiKey}
	if manual != "" {
		set += `, country_code=?, latitude=NULL, longitude=NULL`
		args = append(args, manual)
	} else if code, lat, lon, ok := Geolocate(req.Address); ok {
		set += `, country_code=?, latitude=?, longitude=?`
		args = append(args, code, lat, lon)
	}
	if cert != "" {
		set += `, server_ca=?`
		args = append(args, cert)
	}
	args = append(args, id)
	_, err := db.Exec(`UPDATE nodes SET `+set+` WHERE id = ?`, args...)
	return err
}

func nullIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// --- OVPN downloads (management.py) ---

var remoteLineRe = regexp.MustCompile(`(?i)^\s*remote\s+`)

func remotePlan(n *Node, db *sql.DB) (string, int, [][2]any) {
	domain := panelDomainFor(db)
	if domain == "" {
		if strings.TrimSpace(n.TunnelAddress) != "" {
			domain = strings.TrimSpace(n.TunnelAddress)
		} else {
			domain = strings.TrimSpace(n.Address)
		}
	}
	fallbacks := [][2]any{}
	// Add current node's own extra ports as immediate fallback lines
	if strings.TrimSpace(n.ExtraPorts) != "" {
		for _, pStr := range strings.Split(n.ExtraPorts, ",") {
			if p, err := strconv.Atoi(strings.TrimSpace(pStr)); err == nil && isValidPort(p) && p != n.OVPNPort {
				fallbacks = append(fallbacks, [2]any{domain, p})
			}
		}
	}
	for _, other := range getAllNodes(db) {
		if other.ID != n.ID {
			addr := strings.TrimSpace(other.TunnelAddress)
			if addr == "" {
				addr = strings.TrimSpace(other.Address)
			}
			fallbacks = append(fallbacks, [2]any{addr, other.OVPNPort})
			if strings.TrimSpace(other.ExtraPorts) != "" {
				for _, pStr := range strings.Split(other.ExtraPorts, ",") {
					if p, err := strconv.Atoi(strings.TrimSpace(pStr)); err == nil && isValidPort(p) && p != other.OVPNPort {
						fallbacks = append(fallbacks, [2]any{addr, p})
					}
				}
			}
		}
	}
	return domain, n.OVPNPort, fallbacks
}

func injectRemoteLines(content []byte, domain string, primaryPort int, fallbacks [][2]any) []byte {
	if domain == "" && len(fallbacks) == 0 {
		return content
	}
	// Validate domain and primary port
	if domain != "" && (!isValidHostname(domain) || !isValidPort(primaryPort)) {
		// Invalid domain/port: skip injection, return original content
		return content
	}
	// Validate fallbacks
	validFallbacks := [][2]any{}
	for _, fb := range fallbacks {
		if len(fb) == 2 {
			host, _ := fb[0].(string)
			port, _ := fb[1].(int)
			if isValidHostname(host) && isValidPort(port) {
				validFallbacks = append(validFallbacks, fb)
			}
		}
	}
	if domain == "" && len(validFallbacks) == 0 {
		return content
	}
	text := string(content)
	if !utf8Valid(text) {
		return content
	}
	lines := strings.Split(text, "\n")
	remoteIdx := []int{}
	for i, line := range lines {
		if remoteLineRe.MatchString(line) {
			remoteIdx = append(remoteIdx, i)
		}
	}
	if len(remoteIdx) == 0 {
		return content
	}
	out := append([]string{}, lines...)
	if domain != "" {
		insertAt := remoteIdx[0]
		// If the existing remote line is a placeholder like "remote auto", replace it
		if strings.HasPrefix(strings.TrimSpace(lines[insertAt]), "remote auto") {
			out[insertAt] = fmt.Sprintf("remote %s %d", domain, primaryPort)
		} else {
			out = append(out[:insertAt], append([]string{fmt.Sprintf("remote %s %d", domain, primaryPort)}, out[insertAt:]...)...)
			for i := range remoteIdx {
				remoteIdx[i]++
			}
		}
	}
	fallbackLines := []string{}
	for _, fb := range validFallbacks {
		fallbackLines = append(fallbackLines, fmt.Sprintf("remote %v %v", fb[0], fb[1]))
	}
	if len(fallbackLines) > 0 {
		pos := remoteIdx[len(remoteIdx)-1] + 1
		out = append(out[:pos], append(fallbackLines, out[pos:]...)...)
	}
	trailing := ""
	if strings.HasSuffix(text, "\n") {
		trailing = "\n"
	}
	return []byte(strings.Join(out, "\n") + trailing)
}

func utf8Valid(s string) bool {
	for _, r := range s {
		if r == '\uFFFD' {
			return false
		}
	}
	return true
}

// isValidHostname validates a hostname (domain name or IP address).
func isValidHostname(s string) bool {
	if len(s) == 0 || len(s) > 255 {
		return false
	}
	// Allow IP addresses
	if ip := net.ParseIP(s); ip != nil {
		return true
	}
	// Hostname validation: labels separated by dots, each label 1-63 chars,
	// alphanumeric plus hyphen, not starting/ending with hyphen.
	for _, label := range strings.Split(s, ".") {
		if len(label) == 0 || len(label) > 63 {
			return false
		}
		for i, r := range label {
			if (i == 0 || i == len(label)-1) && r == '-' {
				return false
			}
			if !((r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-') {
				return false
			}
		}
	}
	return true
}

// isValidPort validates a port number.
func isValidPort(p int) bool {
	return p > 0 && p <= 65535
}

// DownloadOVPNClient returns the rewritten .ovpn bytes for one user, or nil.
func DownloadOVPNClient(userID, nodeID int64, db *sql.DB) []byte {
	n := GetNodeByID(db, nodeID)
	if n == nil {
		return nil
	}
	domain, port, fallbacks := remotePlan(n, db)
	c := NodeClient(n, PanelIDFor(db))
	content := c.DownloadOVPNBytes(strconv.FormatInt(userID, 10))
	if content == nil {
		return nil
	}
	return injectRemoteLines(content, domain, port, fallbacks)
}

// DownloadAllOVPNClients returns a ZIP of every user's .ovpn, or nil.
func DownloadAllOVPNClients(nodeID int64, db *sql.DB) []byte {
	n := GetNodeByID(db, nodeID)
	if n == nil {
		return nil
	}
	domain, port, fallbacks := remotePlan(n, db)
	c := NodeClient(n, PanelIDFor(db))
	buf := &bytes.Buffer{}
	zw := zip.NewWriter(buf)
	for _, u := range allUsers(db) {
		raw := c.DownloadOVPNBytes(strconv.FormatInt(u.id, 10))
		if raw == nil {
			continue
		}
		w, err := zw.Create(u.name + ".ovpn")
		if err != nil {
			continue
		}
		_, _ = w.Write(injectRemoteLines(raw, domain, port, fallbacks))
	}
	_ = zw.Close()
	return buf.Bytes()
}

type userRef struct {
	id   int64
	name string
}

func allUsers(db *sql.DB) []userRef {
	rows, err := db.Query(`SELECT id, name FROM users`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []userRef
	for rows.Next() {
		var u userRef
		if err := rows.Scan(&u.id, &u.name); err != nil {
			return out
		}
		out = append(out, u)
	}
	return out
}

// --- user fan-outs (management.py) ---

// DeleteUserOnAllNodes deletes a user from every active node.
func DeleteUserOnAllNodes(userID int64, db *sql.DB) map[string]any {
	nodes := getActiveNodes(db)
	if len(nodes) == 0 {
		return map[string]any{"ok": true, "failed": []string{}}
	}
	pid := PanelIDFor(db)
	uid := strconv.FormatInt(userID, 10)
	calls := make([]func() any, 0, len(nodes))
	for _, n := range nodes {
		c := NodeClient(n, pid)
		calls = append(calls, func() any { return c.DeleteUser(uid) })
	}
	results := GatherBounded(calls)
	failed := []string{}
	for i, n := range nodes {
		if ok, _ := results[i].(bool); !ok {
			failed = append(failed, n.Name)
		}
	}
	return map[string]any{"ok": len(failed) == 0, "failed": failed}
}

// --- HTTP handlers (backend) ---

// Handler serves the /nodes routes; it borrows the auth service's DB handle
// and middleware.
type Handler struct {
	svc          *auth.Service
	OnNodeChange func(op string)
}

func (h *Handler) notifyChange(op string) {
	if h != nil && h.OnNodeChange != nil {
		h.OnNodeChange(op)
	}
}

// NewHandler builds the node router over the shared auth service.
func NewHandler(svc *auth.Service) *Handler {
	if svc != nil {
		AuditDB = svc.DB
	}
	return &Handler{svc: svc}
}

// Mount registers the /nodes routes relative to the caller's prefix.
func (h *Handler) Mount(mux *http.ServeMux) {
	owner := func(fn http.HandlerFunc) http.HandlerFunc { return h.svc.RequireOwner(fn) }
	user := func(fn http.HandlerFunc) http.HandlerFunc { return h.svc.RequireUser(fn) }

	h.register(mux, "POST /nodes/", owner(h.handleAddNode))
	h.register(mux, "POST /nodes", owner(h.handleAddNode))
	h.register(mux, "POST /nodes/test", owner(h.handleTestNode))
	h.register(mux, "PUT /nodes/{node_id}", owner(h.handleUpdateNode))
	h.register(mux, "POST /nodes/{node_id}/repin", owner(h.handleRepin))
	h.register(mux, "PUT /nodes/{node_id}/dns", owner(h.handleNodeDNS))
	h.register(mux, "PUT /nodes/{node_id}/ipv6", owner(h.handleNodeIPv6))
	h.register(mux, "PUT /nodes/{node_id}/ports", owner(h.handleNodePorts))
	h.register(mux, "POST /nodes/{node_id}/restart", owner(h.handleNodeRestart))
	h.register(mux, "POST /nodes/{node_id}/renew-cert", owner(h.handleNodeRenewCert))
	h.register(mux, "POST /nodes/{node_id}/update", owner(h.handleNodeUpdate))
	h.register(mux, "GET /nodes/", owner(h.handleListNodes))
	h.register(mux, "GET /nodes", owner(h.handleListNodes))
	h.register(mux, "GET /nodes/ovpn/{uuid}/{node_id}", user(h.handleDownloadOVPN))
	h.register(mux, "GET /nodes/ovpn/id/{user_id}/{node_id}", user(h.handleDownloadOVPN))
	h.register(mux, "GET /nodes/ovpn-all/{node_id}", owner(h.handleDownloadAllOVPN))
	h.register(mux, "GET /nodes/{first}/{second}", owner(h.handleNodeSubresource))
	h.register(mux, "DELETE /nodes/{node_id}", owner(h.handleDeleteNode))
}

// handleNodeSubresource owns the "/nodes/{id}/<word>" GET routes.
//
// Go's ServeMux cannot rank "/nodes/ovpn-all/{id}" above "/nodes/{id}/status"
// (each is more specific in a different segment) and panics at registration,
// while FastAPI resolved the overlap by declaration order. Both live here:
// "/nodes/ovpn-all/{id}" is a strict subset of "/nodes/{first}/{second}", so it
// wins on specificity, and everything else lands in this switch.
func (h *Handler) handleNodeSubresource(w http.ResponseWriter, r *http.Request) {
	r.SetPathValue("node_id", r.PathValue("first"))
	switch r.PathValue("second") {
	case "status":
		h.handleNodeStatus(w, r)
	case "logs":
		h.handleNodeLogs(w, r)
	default:
		auth.WriteDetail(w, http.StatusNotFound, "Not Found")
	}
}

func (h *Handler) register(mux *http.ServeMux, pattern string, fn http.HandlerFunc) {
	mux.HandleFunc(pattern, fn)
}

func (h *Handler) nodeByID(r *http.Request) *Node {
	id, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		return nil
	}
	return GetNodeByID(h.svc.DB(), id)
}

func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1024*1024)
	return json.NewDecoder(r.Body).Decode(v) == nil
}

func (h *Handler) handleAddNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	if req.Cert == nil || *req.Cert == "" {
		auth.WriteValidation(w, "cert", "A node certificate (PEM) is required to add a node")
		return
	}
	if req.Name == "" || strings.TrimSpace(req.Name) == "" {
		auth.WriteValidation(w, "name", "Node name is required")
		return
	}
	if getNodeByName(h.svc.DB(), req.Name) != nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: fmt.Sprintf("A node named '%s' already exists. Choose a different name.", req.Name)})
		return
	}
	ok, msg := AddNodeHandler(req, h.svc.DB())
	if ok {
		h.notifyChange("create")
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node added successfully"})
		return
	}
	if msg == "" {
		msg = "Node unreachable — install offline and configure after registration."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: msg})
}

func (h *Handler) handleTestNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	if strings.TrimSpace(req.key()) == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "API key is required."})
		return
	}
	serverCA := ""
	if req.Cert != nil && strings.TrimSpace(*req.Cert) != "" {
		serverCA = strings.TrimSpace(*req.Cert)
	} else {
		serverCA = FetchServerCert(req.Address, req.port(), 5*time.Second)
	}
	c, err := NewClient(req.Address, req.port(), req.key(), serverCA, PanelIDFor(h.svc.DB()), 0)
	if err != nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Invalid address: " + err.Error()})
		return
	}
	if c.CheckNode() {
		data := map[string]any{"reachable": true}
		if serverCA != "" {
			data["cert"] = serverCA
		}
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node is reachable.", Data: data})
		return
	}
	msg := c.ConflictMsg()
	if msg == "" {
		msg = "Node unreachable — check address (public IP, not 10.x/192.168.x unless shared LAN), service port (2083, not the 1194 VPN port), and the exact API key."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: msg})
}

func (h *Handler) handleUpdateNode(w http.ResponseWriter, r *http.Request) {
	var req nodeCreate
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	id, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if clash := getNodeByName(h.svc.DB(), req.Name); clash != nil && clash.ID != id {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: fmt.Sprintf("Another node is already named '%s'.", req.Name)})
		return
	}
	ok, msg := UpdateNodeHandler(id, req, h.svc.DB())
	if ok {
		h.notifyChange("update")
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: ok, Msg: msg})
}

func (h *Handler) handleNodeStatus(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node status retrieved successfully", Data: GetNodeStatus(h.svc.DB(), n.ID)})
}

func (h *Handler) handleRepin(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	host, port, _ := parseAddress(n.Address, n.Port)
	pem := FetchServerCert(host, port, 0)
	if pem == "" {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Could not fetch the node's certificate."})
		return
	}
	_, _ = h.svc.DB().Exec(`UPDATE nodes SET server_ca = ? WHERE id = ?`, pem, n.ID)
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Certificate pin updated.", Data: map[string]any{"repinned": true}})
}

func (h *Handler) handleNodeLogs(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	level := r.URL.Query().Get("level")
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit == 0 {
		limit = 100
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Node logs retrieved successfully", Data: c.GetLogs(level, limit)})
}

func (h *Handler) handleNodeDNS(w http.ResponseWriter, r *http.Request) {
	var req struct {
		DNS1 *string `json:"dns1"`
		DNS2 *string `json:"dns2"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.DNS1 == nil && req.DNS2 == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide dns1 and/or dns2."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	applied := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, DNS1: req.DNS1, DNS2: req.DNS2})
	if applied != true {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "The node rejected the DNS update — check the addresses are valid IPs and that the node is reachable."})
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "DNS settings applied on the node.", Data: map[string]any{"dns1": req.DNS1, "dns2": req.DNS2}})
}

func (h *Handler) handleNodeIPv6(w http.ResponseWriter, r *http.Request) {
	var req struct {
		EnableIPv6 *bool   `json:"enable_ipv6"`
		IPv6Prefix *string `json:"ipv6_prefix"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.EnableIPv6 == nil && req.IPv6Prefix == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide enable_ipv6 and/or ipv6_prefix."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	applied := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, EnableIPv6: req.EnableIPv6, IPv6Prefix: req.IPv6Prefix})
	if applied != true {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "The node rejected the IPv6 update — check the prefix is a valid IPv6 network and that the node is reachable."})
		return
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "IPv6 settings applied on the node.", Data: map[string]any{"enable_ipv6": req.EnableIPv6, "ipv6_prefix": req.IPv6Prefix}})
}

func (h *Handler) handleNodePorts(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ExtraPorts *string `json:"extra_ports"`
	}
	if !decodeBody(w, r, &req) {
		auth.WriteValidation(w, "body", "Invalid request body")
		return
	}
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	if req.ExtraPorts == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Provide extra_ports — a comma-separated port list, or an empty string to clear."})
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	answer := c.UpdateConfig(UpdateConfigParams{TunnelAddress: n.TunnelAddress, Protocol: n.Protocol, OVPNPort: n.OVPNPort, ExtraPorts: req.ExtraPorts, ReturnEnvelope: true})
	if answer == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Node unreachable — the ports were not changed."})
		return
	}
	env, _ := answer.(map[string]any)
	success, _ := env["success"].(bool)
	msg, _ := env["msg"].(string)
	if msg == "" {
		if success {
			msg = "Extra VPN ports applied on the node."
		} else {
			msg = "The node rejected the extra ports."
		}
	}
	if success {
		// Persist extra_ports in the database
		_, _ = h.svc.DB().Exec(`UPDATE nodes SET extra_ports = ? WHERE id = ?`, *req.ExtraPorts, n.ID)
		n.ExtraPorts = *req.ExtraPorts
	}
	data := env["data"]
	if data == nil && success {
		data = map[string]any{"extra_ports": *req.ExtraPorts}
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: success, Msg: msg, Data: data})
}

func (h *Handler) nodeEnvelopeAction(w http.ResponseWriter, r *http.Request, call func(*Client) map[string]any, unreachable string) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found")
		return
	}
	c := NodeClient(n, PanelIDFor(h.svc.DB()))
	answer := call(c)
	if answer == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: unreachable})
		return
	}
	success, _ := answer["success"].(bool)
	msg, _ := answer["msg"].(string)
	if msg == "" {
		msg = "Request processed."
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: success, Msg: msg, Data: answer["data"]})
}

func (h *Handler) handleNodeRestart(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.RestartVPN() }, "Node unreachable — the restart was not requested.")
}

func (h *Handler) handleNodeRenewCert(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.RenewServerCert() }, "Node unreachable — nothing was renewed.")
}

func (h *Handler) handleNodeUpdate(w http.ResponseWriter, r *http.Request) {
	h.nodeEnvelopeAction(w, r, func(c *Client) map[string]any { return c.TriggerUpdate() }, "Node unreachable — the update was not started.")
}

func (h *Handler) handleListNodes(w http.ResponseWriter, r *http.Request) {
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: true, Msg: "Nodes retrieved successfully", Data: listNodes(h.svc.DB())})
}

func (h *Handler) handleDeleteNode(w http.ResponseWriter, r *http.Request) {
	n := h.nodeByID(r)
	if n == nil {
		auth.WriteJSON(w, http.StatusOK, auth.Response{Success: false, Msg: "Failed to delete node"})
		return
	}
	ok := DeleteNodeHandler(n.ID, h.svc.DB())
	msg := "Node deleted successfully"
	if !ok {
		msg = "Failed to delete node"
	} else {
		h.notifyChange("delete")
	}
	auth.WriteJSON(w, http.StatusOK, auth.Response{Success: ok, Msg: msg})
}

func parsePositiveRouteID(raw string) (int64, bool) {
	if raw == "" {
		return 0, false
	}
	for i := 0; i < len(raw); i++ {
		if raw[i] < '0' || raw[i] > '9' {
			return 0, false
		}
	}
	id, err := strconv.ParseInt(raw, 10, 64)
	return id, err == nil && id > 0
}

func (h *Handler) handleDownloadOVPN(w http.ResponseWriter, r *http.Request) {
	uuid := r.PathValue("uuid")
	nodeID, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "OVPN file not found")
		return
	}
	userQuery := `SELECT id, is_active, total, used, expiry_date FROM users WHERE uuid = ?`
	var userLookup any = uuid
	if rawID := r.PathValue("user_id"); rawID != "" {
		id, ok := parsePositiveRouteID(rawID)
		if !ok {
			auth.WriteDetail(w, http.StatusNotFound, "User not found")
			return
		}
		userQuery = `SELECT id, is_active, total, used, expiry_date FROM users WHERE id = ?`
		userLookup = id
	}
	var userID int64
	var active bool
	var total, used sql.NullInt64
	var expiry sql.NullString
	if err := h.svc.DB().QueryRow(userQuery, userLookup).Scan(&userID, &active, &total, &used, &expiry); err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "User not found")
		return
	}
	// Expiry gate mirrors the subscription page (sub.subUser): expired users are
	// refused before the disabled/quota checks.
	if expiry.Valid && expiry.String != "" {
		raw := expiry.String
		if len(raw) > 10 {
			raw = raw[:10]
		}
		if raw < time.Now().Format("2006-01-02") {
			auth.WriteDetail(w, http.StatusForbidden, "User account has expired")
			return
		}
	}
	if !active {
		auth.WriteDetail(w, http.StatusForbidden, "User account is not active")
		return
	}
	if total.Valid && used.Int64 >= total.Int64 {
		auth.WriteDetail(w, http.StatusForbidden, "User traffic limit reached")
		return
	}
	content := DownloadOVPNClient(userID, nodeID, h.svc.DB())
	if content == nil {
		auth.WriteDetail(w, http.StatusNotFound, "OVPN file not found")
		return
	}
	w.Header().Set("Content-Type", "application/x-openvpn-profile")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%d.ovpn"`, userID))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(content)
}

func (h *Handler) handleDownloadAllOVPN(w http.ResponseWriter, r *http.Request) {
	nodeID, err := strconv.ParseInt(r.PathValue("node_id"), 10, 64)
	if err != nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found or configs unavailable")
		return
	}
	n := GetNodeByID(h.svc.DB(), nodeID)
	if n == nil {
		auth.WriteDetail(w, http.StatusNotFound, "Node not found or configs unavailable")
		return
	}
	content := DownloadAllOVPNClients(nodeID, h.svc.DB())
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s_all_clients.zip"`, n.Name))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(content)
}
