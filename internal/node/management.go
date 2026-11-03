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
	"encoding/pem"
	"fmt"
	"net"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/anonysec/OVManager/go/internal/audit"
	"github.com/anonysec/OVManager/go/internal/crypto"
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

// dataDir resolves DATA_DIR per call so tests and callers swapping the
// environment stay fresh, falling back to the package default.
func dataDir() string {
	if d := strings.TrimSpace(os.Getenv("DATA_DIR")); d != "" {
		return d
	}
	if DataDir != "" {
		return DataDir
	}
	return "data"
}

func scanNode(row interface{ Scan(...any) error }) (*Node, error) {
	n := &Node{}
	err := row.Scan(&n.ID, &n.Name, &n.Address, &n.TunnelAddress, &n.Protocol, &n.OVPNPort,
		&n.Port, &n.Key, &n.Status, &n.ServerCA, &n.CountryCode, &n.Latitude, &n.Longitude, &n.ExtraPorts)
	if err != nil {
		return nil, err
	}
	if n.Key != "" {
		plain, err := crypto.DecryptSecret(n.Key, dataDir())
		if err != nil {
			return nil, err
		}
		n.Key = plain
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

// CertFingerprint returns the uppercase colon-separated SHA-256 fingerprint of a PEM certificate.
func CertFingerprint(pemStr string) string {
	if !isPEM(pemStr) {
		return ""
	}
	block, _ := pem.Decode([]byte(pemStr))
	if block == nil {
		return ""
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(cert.Raw)
	hexParts := make([]string, len(sum))
	for i, b := range sum {
		hexParts[i] = strings.ToUpper(hex.EncodeToString([]byte{b}))
	}
	return strings.Join(hexParts, ":")
}

func normalizeFingerprint(fp string) string {
	fp = strings.ReplaceAll(fp, ":", "")
	fp = strings.ReplaceAll(fp, " ", "")
	return strings.ToUpper(strings.TrimSpace(fp))
}

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
	out["pinned"] = true
	out["fingerprint"] = CertFingerprint(pinned)
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
		// note: sessions use LongTimeout like management.get_node_status.
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
	Name                string  `json:"name"`
	Address             string  `json:"address"`
	TunnelAddress       *string `json:"tunnel_address"`
	Protocol            string  `json:"protocol"`
	OVPNPort            int     `json:"ovpn_port"`
	Port                int     `json:"port"`
	Key                 *string `json:"key"`
	Cert                *string `json:"cert"`
	ExpectedFingerprint *string `json:"expected_fingerprint"`
	ConfirmFingerprint  *bool   `json:"confirm_fingerprint"`
	Status              *bool   `json:"status"`
	CountryCode         *string `json:"country_code"`
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
	if req.Cert != nil && strings.TrimSpace(*req.Cert) != "" {
		serverCA = strings.TrimSpace(*req.Cert)
	} else {
		serverCA = FetchServerCert(req.Address, req.port(), 5*time.Second)
		if serverCA == "" {
			return false, "Could not fetch certificate from node."
		}
	}
	fp := CertFingerprint(serverCA)
	expectedFP := ""
	if req.ExpectedFingerprint != nil {
		expectedFP = strings.TrimSpace(*req.ExpectedFingerprint)
	}
	if expectedFP == "" {
		return false, fmt.Sprintf("Certificate fingerprint confirmation required before adding node (fingerprint: %s)", fp)
	}
	if normalizeFingerprint(expectedFP) != normalizeFingerprint(fp) {
		return false, fmt.Sprintf("Certificate fingerprint mismatch: expected %s, got %s", expectedFP, fp)
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
		// note: restart-debounce worker (operations/restart_debounce.py) is
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
	storedKey := req.key()
	if enc, err := crypto.EncryptSecret(storedKey, dataDir()); err == nil {
		storedKey = enc
	}
	res, err := db.Exec(
		`INSERT INTO nodes (name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca, country_code, latitude, longitude)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		req.Name, req.Address, req.tunnel(), req.protocol(), req.ovpnPort(), req.port(),
		storedKey, req.status(), nullIfEmpty(serverCA), cc, lat, lon,
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
	storedKey := apiKey
	if enc, err := crypto.EncryptSecret(storedKey, dataDir()); err == nil {
		storedKey = enc
	}
	set := `name=?, address=?, tunnel_address=?, protocol=?, ovpn_port=?, port=?, status=?, key=?`
	args := []any{req.Name, req.Address, req.tunnel(), req.protocol(), req.ovpnPort(), req.port(), req.status(), storedKey}
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
