// the connection/health registry, fan-out bounds, sync workers, diagnostics
// and the node management handlers.
package node

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"database/sql"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/anonysec/OVManager/internal/audit"
)

var (
	AuditDB           func() *sql.DB
	unverifiedNodesMu sync.Mutex
	unverifiedNodes   = make(map[int64]bool)
)

func (c *Client) recordTLSUnverified() {
	if c == nil || c.NodeID == 0 {
		return
	}
	unverifiedNodesMu.Lock()
	already := unverifiedNodes[c.NodeID]
	if !already {
		unverifiedNodes[c.NodeID] = true
	}
	unverifiedNodesMu.Unlock()
	if already {
		return
	}
	if AuditDB != nil {
		if db := AuditDB(); db != nil {
			audit.Record(db, "system", "node.tls_unverified", "critical",
				fmt.Sprintf("SECURITY ALERT: Node %d TLS unverified fallback to %s. API key transmitted without peer verification!", c.NodeID, c.address),
				map[string]any{
					"node_id":  c.NodeID,
					"target":   c.address,
					"severity": "CRITICAL",
					"risk":     "active_mitm_possible",
				})
		}
	}
}

const (
	Timeout     = 10 * time.Second
	LongTimeout = 30 * time.Second
)

// Response-body caps for node reads: http.Client.Timeout bounds time, not bytes.
// A compromised node (or a MitM once NODE_TLS_INSECURE_FALLBACK is on) could
// otherwise stream an unbounded body and exhaust the panel's RAM.
const (
	// maxNodeBody is the cap for small JSON status/usage envelopes from a node.
	maxNodeBody = 1 << 20 // 1 MiB
	// MaxNodeBody is the exported alias of maxNodeBody.
	MaxNodeBody = maxNodeBody
	// maxNodeBodyJSON is the per-endpoint cap for JSON responses.
	maxNodeBodyJSON = 1 << 20 // 1 MiB: JSON status/usage envelopes
	// MaxNodeBodyJSON is the exported alias.
	MaxNodeBodyJSON = maxNodeBodyJSON
	// maxNodeBodyOVPN is the larger (but still finite) cap for an .ovpn profile.
	maxNodeBodyOVPN = 10 << 20 // 10 MiB: downloaded .ovpn profile
	// maxNodeBodyBackup caps a node's backup archive (PKI + state).
	maxNodeBodyBackup = 256 << 20 // 256 MiB: node backup archive
	// MaxNodeBodyOVPN is the exported alias.
	MaxNodeBodyOVPN = maxNodeBodyOVPN
)

// Node is the columns of a nodes row the node package needs.
type Node struct {
	ID            int64
	Name          string
	Address       string
	TunnelAddress string
	Protocol      string
	OVPNPort      int
	Port          int
	Key           string
	Status        bool
	ServerCA      sql.NullString
	CountryCode   sql.NullString
	Latitude      sql.NullFloat64
	Longitude     sql.NullFloat64
	ExtraPorts    string
}

type Client struct {
	address   string // host:port as dialled
	headers   map[string]string
	scheme    string
	pinPEM    string // "" = no pin (default trust + optional fallback)
	NodeID    int64
	checkName bool // whether the pin must also carry the dial name
	// panelID is the per-request X-Panel-ID for clients that own their
	// connection (NodeID == 0); cached clients read it from the registry.
	panelID string

	mu          sync.Mutex
	tlsVerified *bool
	conflictMsg string

	transportMu  sync.Mutex
	transport    *http.Transport
	fallbackUsed bool
}

// NewClient builds a client for address:port. serverCA is the stored pin PEM
// ("" = none). panelID stamps the X-Panel-ID header when non-empty.
func NewClient(address string, port int, apiKey, serverCA, panelID string, nodeID int64) (*Client, error) {
	host, target, err := parseAddress(address, port)
	if err != nil {
		return nil, err
	}
	c := &Client{
		address:   net.JoinHostPort(host, strconv.Itoa(target)),
		scheme:    "https",
		headers:   map[string]string{"key": apiKey},
		NodeID:    nodeID,
		checkName: checkHostname(host),
	}
	// net.JoinHostPort brackets IPv6; strip for URL building is not needed.
	if strings.Contains(host, ":") {
		c.address = "[" + host + "]:" + strconv.Itoa(target)
	}
	c.panelID = panelID
	if serverCA != "" {
		if !isPEM(serverCA) {
			return nil, errors.New("Node has a pinned certificate but it is not a PEM certificate")
		}
		c.pinPEM = serverCA
	}
	return c, nil
}

// resolution (an explicit port in the address wins over the row port).
func parseAddress(raw string, port int) (string, int, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", 0, errors.New("Node address must contain a hostname or IP")
	}
	s := raw
	if !strings.Contains(s, "://") {
		s = "//" + s
	}
	u, err := url.Parse(s)
	if err != nil {
		return "", 0, errors.New("Node address must contain a hostname or IP")
	}
	host := u.Hostname()
	if host == "" {
		return "", 0, errors.New("Node address must contain a hostname or IP")
	}
	target := port
	if p := u.Port(); p != "" {
		n, err := strconv.Atoi(p)
		if err != nil {
			return "", 0, errors.New("Node address contains an invalid port")
		}
		target = n
	}
	return host, target, nil
}

// top of the pin; an IP literal is not; anything unparsable stays strict.
func checkHostname(host string) bool {
	if host == "" {
		return true
	}
	if net.ParseIP(host) != nil {
		return false
	}
	return true
}

func isPEM(v string) bool { return strings.Contains(v, "BEGIN CERTIFICATE") }

// insecureFallback reads NODE_TLS_INSECURE_FALLBACK (default false = fail
// closed). pydantic treats true/1/yes/on as true, case-insensitively.
// insecureFallback reads NODE_TLS_INSECURE_FALLBACK (default false = fail
// closed). pydantic treats true/1/yes/on as true, case-insensitively.
func insecureFallback() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("NODE_TLS_INSECURE_FALLBACK"))) {
	case "1", "true", "yes", "on", "t", "y":
		return true
	default:
		return false
	}
}

func pinnedTLSConfig(pinPEM string, address string, checkName bool) (*tls.Config, error) {
	block, _ := pem.Decode([]byte(pinPEM))
	if block == nil || block.Type != "CERTIFICATE" {
		return nil, errors.New("pinned certificate is not a valid PEM certificate")
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	pool.AddCert(cert)
	if checkName {
		host, _, _ := net.SplitHostPort(address)
		return &tls.Config{RootCAs: pool, ServerName: strings.Trim(host, "[]")}, nil
	}
	// // Pin-only: verify the chain against the pin, ignore the name (IP dial).
	// InsecureSkipVerify: true here does NOT disable verification; it only skips
	// the default system-CA check. The actual verification is done by
	// VerifyPeerCertificate, which validates the leaf certificate against the
	// pinned CA (pool). This is the standard Go pattern for certificate pinning.
	return &tls.Config{
		InsecureSkipVerify:     true, // #nosec G402 // TOFU certificate pinning
		SessionTicketsDisabled: true,
		VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
			if len(rawCerts) == 0 {
				return errors.New("node presented no certificate")
			}
			leaf, err := x509.ParseCertificate(rawCerts[0])
			if err != nil {
				return err
			}
			_, err = leaf.Verify(x509.VerifyOptions{Roots: pool})
			return err
		},
	}, nil
}

type reqOpts struct {
	jsonBody  any
	params    url.Values
	timeout   time.Duration
	allowFail bool // require_success=false: return envelope even on success:false
	rawHeader map[string]string
	useNumber bool
}

// TLSVerified reports whether the last request verified (nil = never connected).
func (c *Client) TLSVerified() *bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.tlsVerified
}

func (c *Client) TLSMode() string {
	v := c.TLSVerified()
	if v == nil {
		return "unknown"
	}
	if *v {
		return "verified"
	}
	return "unverified-self-signed"
}

// ConflictMsg is the node's own 409 explanation, or "".
func (c *Client) ConflictMsg() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.conflictMsg
}

func (c *Client) setVerified(v bool) {
	c.mu.Lock()
	c.tlsVerified = &v
	c.mu.Unlock()
}

func (c *Client) cachedTransport() *http.Transport {
	c.transportMu.Lock()
	defer c.transportMu.Unlock()
	if c.transport != nil {
		return c.transport
	}
	var cfg *tls.Config
	if c.pinPEM != "" {
		var err error
		cfg, err = pinnedTLSConfig(c.pinPEM, c.address, c.checkName)
		if err != nil {
			c.transport = &http.Transport{}
			return c.transport
		}
	}
	c.transport = &http.Transport{TLSClientConfig: cfg}
	return c.transport
}

type nodeError struct {
	node   string
	status int
	msg    string
}

func (e *nodeError) Error() string {
	if e.status != 0 {
		return fmt.Sprintf("node %s: HTTP %d: %s", e.node, e.status, e.msg)
	}
	if e.msg != "" {
		return fmt.Sprintf("node %s: %s", e.node, e.msg)
	}
	return fmt.Sprintf("node %s: unreachable", e.node)
}

// request runs one RPC and returns the parsed envelope (nil on any failure),
type envelope struct {
	Success  bool            `json:"success"`
	Msg      string          `json:"msg"`
	Data     json.RawMessage `json:"data"`
	Conflict bool            `json:"conflict"`
}

func do[T any](c *Client, method, path string, body any, opts reqOpts) (T, error) {
	var zero T
	if body != nil {
		opts.jsonBody = body
	}
	if opts.timeout == 0 {
		opts.timeout = Timeout
	}
	env, err := c.requestInner(method, path, opts)
	if err != nil {
		return zero, err
	}
	if env == nil {
		return zero, &nodeError{node: c.address}
	}
	if !env.Success && !opts.allowFail {
		return zero, &nodeError{node: c.address, msg: env.Msg}
	}
	if len(env.Data) == 0 || string(env.Data) == "null" {
		return zero, nil
	}
	var out T
	if err := json.Unmarshal(env.Data, &out); err != nil {
		return zero, &nodeError{node: c.address, msg: env.Msg}
	}
	return out, nil
}

func (c *Client) requestInner(method, path string, o reqOpts) (*envelope, error) {
	if o.timeout == 0 {
		o.timeout = Timeout
	}
	hc := &http.Client{Transport: c.cachedTransport(), Timeout: o.timeout}
	env, err := c.send(hc, method, path, o)
	if err == nil {
		// The pin config was already applied inside cachedTransport(): a
		// bad pin fails at dial time, never here.
		c.setVerified(true)
		if c.NodeID != 0 {
			Record(c.NodeID, true)
		}
		return env, nil
	}
	if c.pinPEM != "" {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		if c.NodeID != 0 {
			Record(c.NodeID, false)
		}
		return nil, err
	}
	if !isTLSError(err) || !insecureFallback() || c.fallbackUsed {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		if c.NodeID != 0 {
			Record(c.NodeID, false)
		}
		return nil, err
	}
	log.Printf("WARNING: node %s TLS fell back to unverified (NODE_TLS_INSECURE_FALLBACK)", c.address)
	c.fallbackUsed = true
	insecure := &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}
	hc2 := &http.Client{Transport: insecure, Timeout: o.timeout}
	env2, err2 := c.send(hc2, method, path, o)
	if err2 != nil {
		if c.NodeID != 0 {
			Record(c.NodeID, false)
		}
		return nil, err2
	}
	c.setVerified(false)
	c.recordTLSUnverified()
	if c.NodeID != 0 {
		Record(c.NodeID, true)
	}
	return env2, nil
}

// send performs (and retries once on 429) the request, applying the 409 /
func (c *Client) send(hc *http.Client, method, path string, o reqOpts) (*envelope, error) {
	c.mu.Lock()
	c.conflictMsg = ""
	c.mu.Unlock()

	var body []byte
	if o.jsonBody != nil {
		body, _ = json.Marshal(o.jsonBody)
	}
	resp, err := c.roundtrip(hc, method, path, o, body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusTooManyRequests {
		wait := retryAfterS(resp.Header.Get("Retry-After"))
		_ = resp.Body.Close()
		time.Sleep(wait)
		resp, err = c.roundtrip(hc, method, path, o, body)
		if err != nil {
			return nil, err
		}
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusConflict {
		msg := conflictMessage(resp)
		c.mu.Lock()
		c.conflictMsg = msg
		c.mu.Unlock()
		return &envelope{Success: false, Msg: msg, Conflict: true}, nil
	}
	if resp.StatusCode != http.StatusOK {
		return nil, &nodeError{node: c.address, status: resp.StatusCode}
	}
	// Bound the read so an oversized body is a clean failure, not a partial
	// JSON object decoded into data.
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxNodeBodyJSON+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > maxNodeBodyJSON {
		return nil, fmt.Errorf("node response body exceeds %d bytes", maxNodeBodyJSON)
	}
	var env envelope
	dec := json.NewDecoder(bytes.NewReader(raw))
	if o.useNumber {
		dec.UseNumber()
	}
	if err := dec.Decode(&env); err != nil {
		return nil, nil
	}
	return &env, nil
}

// panelIDHeader resolves the X-Panel-ID to send. Cached clients read it from
// the registry under connMu (NodeClient is the only writer); clients that own
// their connection (NodeID == 0) read their own field.
func (c *Client) panelIDHeader() string {
	if c.NodeID == 0 {
		return c.panelID
	}
	connMu.Lock()
	defer connMu.Unlock()
	if conn, ok := connections[c.NodeID]; ok {
		return conn.panelID
	}
	return c.panelID
}

func (c *Client) roundtrip(hc *http.Client, method, path string, o reqOpts, body []byte) (*http.Response, error) {
	rawURL := c.scheme + "://" + c.address + path
	if len(o.params) > 0 {
		rawURL += "?" + o.params.Encode()
	}
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, rawURL, rdr) // #nosec // address comes from trusted node record
	if err != nil {
		return nil, err
	}
	for k, v := range c.headers {
		req.Header.Set(k, v)
	}
	if pid := c.panelIDHeader(); pid != "" {
		req.Header.Set("X-Panel-ID", pid)
	}
	for k, v := range o.rawHeader {
		req.Header.Set(k, v)
	}
	req.Header.Set("X-Contract-Version", fmt.Sprint(ContractVersion))
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return hc.Do(req) // #nosec // address comes from trusted node record
}

func retryAfterS(v string) time.Duration {
	f, err := strconv.ParseFloat(strings.TrimSpace(v), 64)
	if err != nil {
		return 5 * time.Second
	}
	if f != f || f < 1 { // NaN or sub-second
		return time.Second
	}
	if f > 60 {
		f = 60
	}
	return time.Duration(f * float64(time.Second))
}

func conflictMessage(resp *http.Response) string {
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, maxNodeBodyJSON+1))
	if len(raw) > maxNodeBodyJSON {
		return "Node is paired with another panel."
	}
	var body map[string]any
	_ = json.Unmarshal(raw, &body)
	for _, key := range []string{"detail", "msg"} {
		if s, ok := body[key].(string); ok && strings.TrimSpace(s) != "" {
			return strings.TrimSpace(s)
		}
		if list, ok := body[key].([]any); ok {
			for _, item := range list {
				if s, ok := item.(string); ok && s != "" {
					return s
				}
			}
		}
	}
	return "Node is paired with another panel."
}

func isTLSError(err error) bool {
	var cv *tls.CertificateVerificationError
	if errors.As(err, &cv) {
		return true
	}
	var unk x509.UnknownAuthorityError
	if errors.As(err, &unk) {
		return true
	}
	var host x509.HostnameError
	if errors.As(err, &host) {
		return true
	}
	var inv x509.CertificateInvalidError
	if errors.As(err, &inv) {
		return true
	}
	var rec tls.RecordHeaderError
	if errors.As(err, &rec) {
		return true
	}
	s := err.Error()
	return strings.Contains(s, "certificate") || strings.Contains(s, "tls:") || strings.Contains(s, "x509:")
}

// CheckNode is a reachability probe (GET /sync/status).
type statusResponse struct {
	Version     string  `json:"version"`
	CPUUsage    float64 `json:"cpu_usage"`
	MemoryUsage float64 `json:"memory_usage"`
	CertExpiry  string  `json:"cert_expiry"`
}

type usageResponse struct {
	Totals       map[string]json.Number `json:"totals"`
	TotalsEpochs map[string]string      `json:"totals_epochs"`
}

type SessionEntry struct {
	CommonName string `json:"common_name"`
	CN         string `json:"cn"`
	Peer       string `json:"peer"`
	TS         string `json:"ts"`
	Action     string `json:"action"`
	Severity   string `json:"severity"`
	Reason     string `json:"reason"`
	Ongoing    bool   `json:"ongoing"`
}

type EventEntry struct {
	TS       float64         `json:"ts"`
	LastSeen float64         `json:"last_seen"`
	Ongoing  json.RawMessage `json:"ongoing"`
	CN       string          `json:"cn"`
	Action   string          `json:"action"`
	Severity string          `json:"severity"`
	Reason   string          `json:"reason"`
	Peer     string          `json:"peer"`
	Source   string          `json:"source"`
}

type SessionsResponse struct {
	LiveSessions     []SessionEntry  `json:"live_sessions"`
	StaleMarkers     []SessionEntry  `json:"stale_markers"`
	LiveCount        int             `json:"live_count"`
	StaleMarkerCount int             `json:"stale_marker_count"`
	AuthErrors       int             `json:"auth_errors"`
	AuthErrorsByCN   map[string]int  `json:"auth_errors_by_cn"`
	Rejects          int             `json:"rejects"`
	PolicyRejects    int             `json:"policy_rejects"`
	WarnRejects      int             `json:"warn_rejects"`
	Events           []EventEntry    `json:"events"`
	LastError        json.RawMessage `json:"last_error"`
}

type LogRecord struct {
	Level   string `json:"level"`
	Time    string `json:"time"`
	Message string `json:"message"`
	Where   string `json:"where"`
}

type LogsResponse struct {
	Records   []LogRecord `json:"records"`
	LastError string      `json:"last_error"`
	Errors1h  int         `json:"errors_1h"`
}

type DisconnectResponse struct {
	RemovedMarkers []string `json:"removed_markers"`
	KilledSessions int      `json:"killed_sessions"`
}

type LimitsBatchResponse struct {
	Applied int               `json:"applied"`
	Failed  []json.RawMessage `json:"failed"`
}

func (c *Client) CheckNode() bool {
	_, err := do[statusResponse](c, http.MethodGet, "/sync/status", nil, reqOpts{jsonBody: map[string]any{}})
	return err == nil
}

func (c *Client) GetStatus() (*statusResponse, error) {
	s, err := do[statusResponse](c, http.MethodGet, "/sync/status", nil, reqOpts{jsonBody: map[string]any{}})
	if err != nil {
		return nil, err
	}
	return &s, nil
}

func (c *Client) GetNodeInfo() map[string]any {
	s, err := c.GetStatus()
	if err != nil {
		return nil
	}
	return map[string]any{
		"version": s.Version, "cpu_usage": s.CPUUsage,
		"memory_usage": s.MemoryUsage, "cert_expiry": s.CertExpiry,
	}
}

func (c *Client) GetUsage(timeout time.Duration) (*usageResponse, error) {
	if timeout == 0 {
		timeout = LongTimeout
	}
	u, err := do[usageResponse](c, http.MethodGet, "/sync/usage", nil, reqOpts{timeout: timeout, useNumber: true})
	if err != nil {
		return nil, err
	}
	return &u, nil
}

// UpdateConfigParams carries the optional per-node endpoint settings.
type UpdateConfigParams struct {
	TunnelAddress  string
	Protocol       string
	OVPNPort       int
	DNS1           *string
	DNS2           *string
	EnableIPv6     *bool
	IPv6Prefix     *string
	ExtraPorts     *string
	ReturnEnvelope bool
}

// UpdateConfig applies OpenVPN endpoint settings on the node. It returns bool
// by default, or the node's full envelope (or a conflict envelope / nil) when
// ReturnEnvelope is set.
func (c *Client) UpdateConfig(p UpdateConfigParams) any {
	payload := map[string]any{
		"tunnel_address":  p.TunnelAddress,
		"protocol":        p.Protocol,
		"ovpn_port":       p.OVPNPort,
		"set_new_setting": true,
	}
	if p.DNS1 != nil {
		payload["dns1"] = *p.DNS1
	}
	if p.DNS2 != nil {
		payload["dns2"] = *p.DNS2
	}
	if p.EnableIPv6 != nil {
		payload["enable_ipv6"] = *p.EnableIPv6
	}
	if p.IPv6Prefix != nil {
		payload["ipv6_prefix"] = *p.IPv6Prefix
	}
	if p.ExtraPorts != nil {
		payload["extra_ports"] = *p.ExtraPorts
	}
	if p.ReturnEnvelope {
		env, err := c.requestInner(http.MethodPost, "/sync/config", reqOpts{jsonBody: payload, timeout: LongTimeout, allowFail: true})
		if err != nil || env == nil {
			return any(nil)
		}
		return map[string]any{"success": env.Success, "msg": env.Msg, "data": env.Data, "conflict": env.Conflict}
	}
	_, err := do[emptyResponse](c, http.MethodPost, "/sync/config", payload, reqOpts{timeout: LongTimeout})
	return err == nil
}

type emptyResponse struct{}

func (c *Client) RestartVPN() error {
	_, err := do[emptyResponse](c, http.MethodPost, "/sync/restart", nil, reqOpts{timeout: LongTimeout, allowFail: true})
	return err
}

func (c *Client) RenewServerCert() error {
	_, err := do[emptyResponse](c, http.MethodPost, "/sync/renew-cert", nil, reqOpts{timeout: LongTimeout, allowFail: true})
	return err
}

func (c *Client) TriggerUpdate() error {
	_, err := do[emptyResponse](c, http.MethodPost, "/sync/update", nil, reqOpts{timeout: LongTimeout, allowFail: true})
	return err
}

func (c *Client) DeleteUser(uid string) bool {
	_, err := do[emptyResponse](c, http.MethodDelete, "/sync/user/"+uid, nil, reqOpts{timeout: 120 * time.Second})
	return err == nil
}

// SetUserLimit pushes a max-logins limit to the node.
// DisconnectUser drops a user's session(s) on the node.
func (c *Client) DisconnectUser(uid string, onlyStale bool, timeout time.Duration) (*DisconnectResponse, error) {
	if timeout <= 0 {
		timeout = LongTimeout
	}
	o := reqOpts{timeout: timeout}
	if onlyStale {
		o.params = url.Values{"only_stale": {"true"}}
	}
	r, err := do[DisconnectResponse](c, http.MethodPost, "/sync/user/"+uid+"/disconnect", nil, o)
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// GetSessions returns the node's live sessions/stale markers.
func (c *Client) GetSessions(commonName string, hours int, timeout time.Duration) (*SessionsResponse, error) {
	if timeout == 0 {
		timeout = LongTimeout
	}
	params := url.Values{"hours": {strconv.Itoa(hours)}}
	if commonName != "" {
		params.Set("common_name", commonName)
	}
	r, err := do[SessionsResponse](c, http.MethodGet, "/sync/sessions", nil, reqOpts{params: params, timeout: timeout})
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// GetLogs returns the node's in-memory log ring.
func (c *Client) GetLogs(level string, limit int) (*LogsResponse, error) {
	level = strings.ToUpper(level)
	switch level {
	case "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL":
	default:
		level = "WARNING"
	}
	if limit < 1 {
		limit = 1
	}
	if limit > 500 {
		limit = 500
	}
	params := url.Values{"level": {level}, "limit": {strconv.Itoa(limit)}}
	r, err := do[LogsResponse](c, http.MethodGet, "/sync/logs", nil, reqOpts{params: params, timeout: LongTimeout})
	if err != nil {
		return nil, err
	}
	return &r, nil
}

// GetRaw fetches raw bytes with the same TLS policy as request. Returns nil on
// any failure or when the body is not an OVPN profile.
func (c *Client) GetRaw(path string, headers map[string]string, timeout time.Duration) []byte {
	if timeout == 0 {
		timeout = Timeout
	}
	body, _ := c.rawInner(path, headers, timeout, false)
	return body
}

func (c *Client) rawInner(path string, headers map[string]string, timeout time.Duration, allowInsecure bool) ([]byte, error) {
	return c.rawInnerLimit(path, headers, timeout, allowInsecure, maxNodeBodyOVPN, validProfile)
}

// rawInnerLimit is rawInner with an explicit body cap and body validator: a
// node backup archive is larger than an .ovpn profile and is not a profile.
func (c *Client) rawInnerLimit(path string, headers map[string]string, timeout time.Duration, allowInsecure bool, limit int64, validate func([]byte) ([]byte, error)) ([]byte, error) {
	do := func(cfg *tls.Config) ([]byte, error) {
		rawURL := c.scheme + "://" + c.address + path
		req, err := http.NewRequest(http.MethodGet, rawURL, nil)
		if err != nil {
			return nil, err
		}
		for k, v := range c.headers {
			req.Header.Set(k, v)
		}
		if pid := c.panelIDHeader(); pid != "" {
			req.Header.Set("X-Panel-ID", pid)
		}
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		hc := &http.Client{Transport: c.cachedTransport(), Timeout: timeout}
		resp, err := hc.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		buf, err := io.ReadAll(io.LimitReader(resp.Body, limit+1))
		if err != nil {
			return nil, err
		}
		if int64(len(buf)) > limit {
			return nil, fmt.Errorf("node response body exceeds %d bytes", limit)
		}
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
		}
		return buf, nil
	}
	if c.pinPEM != "" {
		cfg, err := pinnedTLSConfig(c.pinPEM, c.address, c.checkName)
		if err != nil {
			if c.TLSVerified() != nil {
				c.setVerified(false)
			}
			return nil, err
		}
		buf, err := do(cfg)
		if err != nil {
			if c.TLSVerified() != nil {
				c.setVerified(false)
			}
			return nil, err
		}
		c.setVerified(true)
		return validate(buf)
	}
	buf, err := do(nil)
	if err == nil {
		c.setVerified(true)
		return validate(buf)
	}
	if !isTLSError(err) || !insecureFallback() || c.fallbackUsed {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil, err
	}
	log.Printf("WARNING: node %s TLS fell back to unverified (NODE_TLS_INSECURE_FALLBACK); failing closed on next fallback for this node until restart", c.address)
	c.fallbackUsed = true
	buf, err = do(&tls.Config{InsecureSkipVerify: true}) // #nosec // NODE_TLS_INSECURE_FALLBACK
	if err != nil {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil, err
	}
	c.setVerified(false)
	c.recordTLSUnverified()
	return validate(buf)
}

func validProfile(buf []byte) ([]byte, error) {
	trimmed := bytes.TrimLeft(buf, " \t\r\n")
	if bytes.HasPrefix(trimmed, []byte("client")) || bytes.Contains(buf, []byte("<ca>")) {
		return buf, nil
	}
	return nil, errors.New("invalid response")
}

// DownloadOVPNBytes returns the raw .ovpn file bytes for ZIP bundling.
func (c *Client) DownloadOVPNBytes(uid string) []byte {
	return c.GetRaw("/sync/download/ovpn/"+uid,
		map[string]string{"Accept": "application/x-openvpn-profile"}, 120*time.Second)
}

// GetRawLimit is GetRaw with an explicit body cap: a node backup archive is
// larger than an .ovpn profile and is not a profile.
func (c *Client) GetRawLimit(path string, headers map[string]string, timeout time.Duration, limit int64) []byte {
	if timeout == 0 {
		timeout = Timeout
	}
	body, err := c.rawInnerLimit(path, headers, timeout, false, limit, func(b []byte) ([]byte, error) {
		return b, nil
	})
	if err != nil {
		return nil
	}
	return body
}

// GetBackup fetches the node's backup archive (a gzipped tar of its PKI and
// state). It returns the raw bytes or nil on any failure.
func (c *Client) GetBackup(timeout time.Duration) []byte {
	if timeout == 0 {
		timeout = LongTimeout
	}
	return c.GetRawLimit("/sync/backup", nil, timeout, maxNodeBodyBackup)
}

// DownloadBackup writes the node's backup archive to dest and returns the
// number of bytes written. The node owns its PKI, so the panel keeps a copy
// rather than moving the CA.
func (c *Client) DownloadBackup(dest string, timeout time.Duration) (int64, error) {
	data := c.GetBackup(timeout)
	if len(data) == 0 {
		return 0, errors.New("node returned no backup archive")
	}
	if err := os.WriteFile(dest, data, 0o600); err != nil {
		return 0, err
	}
	return int64(len(data)), nil
}
