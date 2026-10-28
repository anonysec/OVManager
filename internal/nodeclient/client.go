// Package node ports the backend/node package: the mTLS API client,
// the connection/health registry, fan-out bounds, sync workers, diagnostics
// and the node management handlers.
//
// TLS policy (backend): a stored server_ca pin verifies the
// node against exactly that certificate and an SSL failure fails closed. With
// no pin, an SSL failure also fails closed unless NODE_TLS_INSECURE_FALLBACK
// is set, in which case one unverified retry happens with a loud warning.
package nodeclient

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Timeouts mirror backend/node/requests.py.
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
	// MaxNodeBodyOVPN is the exported alias.
	MaxNodeBodyOVPN = maxNodeBodyOVPN
)

// Node is the columns of a nodes row the node package needs.
// Client is the per-node HTTP client (backend/node/requests.NodeRequests).
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

	transportMu       sync.Mutex
	pinnedTransport   *http.Transport
	plainTransport    *http.Transport
	insecureTransport *http.Transport
}

// NewClient builds a client from a Target.
func NewClient(t Target) (*Client, error) {
	host, _, err := ParseAddress(t.Address, t.OVPNPort)
	if err != nil {
		return nil, err
	}
	c := &Client{
		address:   net.JoinHostPort(host, strconv.Itoa(t.OVPNPort)),
		scheme:    "https",
		headers:   map[string]string{"key": t.APIKey},
		NodeID:    t.ID,
		checkName: CheckHostname(host),
	}
	// net.JoinHostPort brackets IPv6; strip for URL building is not needed.
	if strings.Contains(host, ":") {
		c.address = "[" + host + "]:" + strconv.Itoa(t.OVPNPort)
	}
	c.panelID = t.PanelID
	if t.ServerCA != "" {
		if !IsPEM(t.ServerCA) {
			return nil, errors.New("Node has a pinned certificate but it is not a PEM certificate")
		}
		c.pinPEM = t.ServerCA
	}
	return c, nil
}

// parseAddress accepts an optional scheme and mirrors requests.py's host/port
// resolution (an explicit port in the address wins over the row port).
func ParseAddress(raw string, port int) (string, int, error) {
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

// checkHostname mirrors requests.py _check_hostname_for: a name is checked on
// top of the pin; an IP literal is not; anything unparsable stays strict.
func CheckHostname(host string) bool {
	if host == "" {
		return true
	}
	if net.ParseIP(host) != nil {
		return false
	}
	return true
}

func IsPEM(v string) bool { return strings.Contains(v, "BEGIN CERTIFICATE") }

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
	// Pin-only: verify the chain against the pin, ignore the name (IP dial).
	return &tls.Config{
		InsecureSkipVerify: true, //nolint:gosec // replaced by VerifyPeerCertificate below
		VerifyPeerCertificate: func(rawCerts [][]byte, _ [][]*x509.Certificate) error {
			if len(rawCerts) == 0 {
				return errors.New("node presented no certificate")
			}
			leaf, err := x509.ParseCertificate(rawCerts[0])
			if err != nil {
				return err
			}
			intermediates := x509.NewCertPool()
			for i := 1; i < len(rawCerts); i++ {
				if inter, err := x509.ParseCertificate(rawCerts[i]); err == nil {
					intermediates.AddCert(inter)
				}
			}
			opts := x509.VerifyOptions{
				Roots:         pool,
				Intermediates: intermediates,
				KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
			}
			_, err = leaf.Verify(opts)
			return err
		},
	}, nil
}

type ReqOpts struct {
	JSONBody  any
	Params    url.Values
	Timeout   time.Duration
	AllowFail bool // require_success=false: return envelope even on success:false
	RawHeader map[string]string
}

// TLSVerified reports whether the last request verified (nil = never connected).
func (c *Client) TLSVerified() *bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.tlsVerified
}

// TLSMode is the UI-facing connection security (requests.py tls_mode).
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

// cachedTransport returns a reusable *http.Transport for the given TLS config.
// cfg == nil yields a plain transport; the insecure flag selects the
// InsecureSkipVerify transport used only when insecureFallback() is true.
func (c *Client) cachedTransport(cfg *tls.Config, insecure bool) *http.Transport {
	c.transportMu.Lock()
	defer c.transportMu.Unlock()
	if insecure {
		if c.insecureTransport == nil {
			c.insecureTransport = &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}
		}
		return c.insecureTransport
	}
	if cfg == nil {
		if c.plainTransport == nil {
			c.plainTransport = &http.Transport{}
		}
		return c.plainTransport
	}
	if c.pinnedTransport == nil {
		c.pinnedTransport = &http.Transport{TLSClientConfig: cfg}
	}
	return c.pinnedTransport
}

// request runs one RPC and returns the parsed envelope (nil on any failure),
// recording health from this single choke point (requests.py _request).
func (c *Client) Request(method, path string, o ReqOpts) map[string]any {
	result := c.RequestInner(method, path, o)
	if c.NodeID != 0 {
		Record(c.NodeID, result != nil)
	}
	return result
}

func (c *Client) RequestInner(method, path string, o ReqOpts) map[string]any {
	if o.Timeout == 0 {
		o.Timeout = Timeout
	}
	if c.pinPEM != "" {
		cfg, err := pinnedTLSConfig(c.pinPEM, c.address, c.checkName)
		if err != nil {
			if c.TLSVerified() != nil {
				c.setVerified(false)
			}
			return nil
		}
		hc := &http.Client{Transport: c.cachedTransport(cfg, false), Timeout: o.Timeout}
		r, err := c.send(hc, method, path, o)
		if err != nil {
			if c.TLSVerified() != nil {
				c.setVerified(false)
			}
			return nil // pin mismatch/transport: fail closed, never fall back
		}
		c.setVerified(true)
		return r
	}
	hc := &http.Client{Transport: c.cachedTransport(nil, false), Timeout: o.Timeout}
	r, err := c.send(hc, method, path, o)
	if err == nil {
		c.setVerified(true)
		return r
	}
	if !isTLSError(err) {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil
	}
	if !insecureFallback() {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil
	}
	hc2 := &http.Client{Transport: c.cachedTransport(nil, true), Timeout: o.Timeout}
	r2, err2 := c.send(hc2, method, path, o)
	if err2 != nil {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil
	}
	c.setVerified(false)
	return r2
}

// send performs (and retries once on 429) the request, applying the 409 /
// non-200 / success:false rules (requests.py _send).
func (c *Client) send(hc *http.Client, method, path string, o ReqOpts) (map[string]any, error) {
	c.mu.Lock()
	c.conflictMsg = ""
	c.mu.Unlock()

	var body []byte
	if o.JSONBody != nil {
		body, _ = json.Marshal(o.JSONBody)
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
		if o.AllowFail {
			return map[string]any{"success": false, "conflict": true, "msg": msg}, nil
		}
		return nil, nil
	}
	if resp.StatusCode != http.StatusOK {
		return nil, nil
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
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, nil
	}
	if ok, _ := data["success"].(bool); !ok && !o.AllowFail {
		return nil, nil
	}
	return data, nil
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

func (c *Client) roundtrip(hc *http.Client, method, path string, o ReqOpts, body []byte) (*http.Response, error) {
	rawURL := c.scheme + "://" + c.address + path
	if len(o.Params) > 0 {
		rawURL += "?" + o.Params.Encode()
	}
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, rawURL, rdr)
	if err != nil {
		return nil, err
	}
	for k, v := range c.headers {
		req.Header.Set(k, v)
	}
	if pid := c.panelIDHeader(); pid != "" {
		req.Header.Set("X-Panel-ID", pid)
	}
	for k, v := range o.RawHeader {
		req.Header.Set(k, v)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return hc.Do(req)
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

// conflictMessage surfaces the node's own 409 explanation (requests.py).
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

// dataOf returns r["data"] as a map.
//
// A nil result means the node did not answer: the call failed, or the
// response carried no data object. Callers that need to tell "unreachable"
// from "answered with nothing" must see that difference, so this returns
// nil rather than an empty map — an empty map made every "the node is
// unreachable" check dead code, and an unreachable node was reported as
// reachable with zero counters.
//
// A caller that puts the result on the wire goes through orEmpty.
func DataOf(r map[string]any) map[string]any {
	if r == nil {
		return nil
	}
	if d, ok := r["data"].(map[string]any); ok {
		return d
	}
	return map[string]any{}
}

// --- NodeRequests methods (requests.py) ---

// CheckNode is a reachability probe (GET /sync/status).
func (c *Client) CheckNode() bool {
	return c.Request(http.MethodGet, "/sync/status", ReqOpts{JSONBody: map[string]any{}}) != nil
}

// GetNodeInfo returns the node's reported data (GET /sync/status).
func (c *Client) GetNodeInfo() map[string]any {
	return DataOf(c.Request(http.MethodGet, "/sync/status", ReqOpts{JSONBody: map[string]any{}}))
}

// GetUsage returns per-user traffic counters.
func (c *Client) GetUsage(timeout time.Duration) map[string]any {
	if timeout == 0 {
		timeout = LongTimeout
	}
	return DataOf(c.Request(http.MethodGet, "/sync/usage", ReqOpts{Timeout: timeout}))
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
		r := c.Request(http.MethodPost, "/sync/config", ReqOpts{JSONBody: payload, Timeout: LongTimeout, AllowFail: true})
		if r == nil {
			return any(nil)
		}
		return r
	}
	return c.Request(http.MethodPost, "/sync/config", ReqOpts{JSONBody: payload, Timeout: LongTimeout}) != nil
}

// RestartVPN asks the node to restart OpenVPN (envelope even on refusal).
func (c *Client) RestartVPN() map[string]any {
	return c.Request(http.MethodPost, "/sync/restart", ReqOpts{Timeout: LongTimeout, AllowFail: true})
}

// RenewServerCert asks the node to renew its server certificate.
func (c *Client) RenewServerCert() map[string]any {
	return c.Request(http.MethodPost, "/sync/renew-cert", ReqOpts{Timeout: LongTimeout, AllowFail: true})
}

// TriggerUpdate asks the node to run its self-update.
func (c *Client) TriggerUpdate() map[string]any {
	return c.Request(http.MethodPost, "/sync/update", ReqOpts{Timeout: LongTimeout, AllowFail: true})
}

// CreateUser provisions a user on the node.
func (c *Client) CreateUser(name string, maxLogins int, uid string) bool {
	data := map[string]any{"name": name, "max_logins": maxLogins}
	if uid != "" {
		data["id"] = uid
	}
	return c.Request(http.MethodPost, "/sync/user", ReqOpts{JSONBody: data, Timeout: 180 * time.Second}) != nil
}

// ChangeUserStatus activates/deactivates a user on the node.
// DeleteUser removes a user from the node.
func (c *Client) DeleteUser(uid string) bool {
	return c.Request(http.MethodDelete, "/sync/user/"+uid, ReqOpts{Timeout: 120 * time.Second}) != nil
}

// SetUserLimit pushes a max-logins limit to the node.
// DisconnectUser drops a user's session(s) on the node.
func (c *Client) DisconnectUser(uid string, onlyStale bool, timeout time.Duration) map[string]any {
	if timeout <= 0 {
		timeout = LongTimeout
	}
	o := ReqOpts{Timeout: timeout}
	if onlyStale {
		o.Params = url.Values{"only_stale": {"true"}}
	}
	return DataOf(c.Request(http.MethodPost, "/sync/user/"+uid+"/disconnect", o))
}

// ResetUsage zeroes a user's banked counters on the node.
func (c *Client) ResetUsage(uid string) bool {
	r := c.Request(http.MethodPost, "/sync/user/"+uid+"/reset-usage", ReqOpts{Timeout: LongTimeout})
	if r == nil {
		return false
	}
	ok, _ := r["success"].(bool)
	return ok
}

// GetSessions returns the node's live sessions/stale markers.
func (c *Client) GetSessions(commonName string, hours int, timeout time.Duration) map[string]any {
	if timeout == 0 {
		timeout = LongTimeout
	}
	params := url.Values{"hours": {strconv.Itoa(hours)}}
	if commonName != "" {
		params.Set("common_name", commonName)
	}
	return DataOf(c.Request(http.MethodGet, "/sync/sessions", ReqOpts{Params: params, Timeout: timeout}))
}

// GetLogs returns the node's in-memory log ring.
func (c *Client) GetLogs(level string, limit int) map[string]any {
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
	return DataOf(c.Request(http.MethodGet, "/sync/logs", ReqOpts{Params: params, Timeout: LongTimeout}))
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
		hc := &http.Client{Transport: c.cachedTransport(cfg, false), Timeout: timeout}
		resp, err := hc.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		buf, err := io.ReadAll(io.LimitReader(resp.Body, maxNodeBodyOVPN+1))
		if err != nil {
			return nil, err
		}
		if len(buf) > maxNodeBodyOVPN {
			return nil, fmt.Errorf("node response body exceeds %d bytes", maxNodeBodyOVPN)
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
		return validProfile(buf)
	}
	buf, err := do(nil)
	if err == nil {
		c.setVerified(true)
		return validProfile(buf)
	}
	if !isTLSError(err) || !insecureFallback() {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil, err
	}
	buf, err = do(&tls.Config{InsecureSkipVerify: true})
	if err != nil {
		if c.TLSVerified() != nil {
			c.setVerified(false)
		}
		return nil, err
	}
	c.setVerified(false)
	return validProfile(buf)
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
