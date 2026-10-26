// Panel↔node contract parity: the table in internal/node/contract.go must
// describe what the panel's client actually sends and reads, so a node-side
// change the panel cannot absorb fails here first.
package tests

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/printer"
	"go/token"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"

	"github.com/anonysec/OVManager/go/internal/node"
)

// contractProfile is a node-native .ovpn body: the panel has to take it as
// raw text, not as an envelope.
const contractProfile = "client\ndev tun\nremote node-native.example 1194\n<ca>\nMIIB\n</ca>\n"

// route is one node endpoint: a method and a path.
type route struct {
	method string
	path   string
}

func (r route) String() string { return r.method + " " + r.path }

// emit is one place in the panel that sends a node route.
type emit struct {
	file string
	fn   string
	line int
}

// repoPath resolves a repo-relative path from the test directory.
func repoPath(rel string) string { return filepath.Join("..", rel) }

// emittedRoutes scans the node package for every route the client can send.
//
// The scan, not a hand-written list: a route added to the client without a
// contract row has to fail here, and the row's request site has to be the
// function that really sends it.
func emittedRoutes(t *testing.T) map[route][]emit {
	t.Helper()
	out := map[route][]emit{}
	dir := repoPath("internal/node")
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read %s: %v", dir, err)
	}
	for _, entry := range entries {
		name := entry.Name()
		if !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		rel := "internal/node/" + name
		fset := token.NewFileSet()
		f, err := parser.ParseFile(fset, repoPath(rel), nil, 0)
		if err != nil {
			t.Fatalf("parse %s: %v", rel, err)
		}
		for _, decl := range f.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok || fn.Body == nil {
				continue
			}
			ast.Inspect(fn.Body, func(n ast.Node) bool {
				call, ok := n.(*ast.CallExpr)
				if !ok {
					return true
				}
				sel, ok := call.Fun.(*ast.SelectorExpr)
				if !ok {
					return true
				}
				method, path := "", ""
				switch sel.Sel.Name {
				case "request", "requestInner":
					if len(call.Args) < 2 {
						return true
					}
					method, path = methodName(call.Args[0]), pathName(call.Args[1])
				case "GetRaw":
					if len(call.Args) < 1 {
						return true
					}
					method, path = http.MethodGet, pathName(call.Args[0])
				}
				if method == "" || path == "" {
					return true
				}
				r := route{method: method, path: path}
				out[r] = append(out[r], emit{file: rel, fn: fn.Name.Name, line: fset.Position(call.Pos()).Line})
				return true
			})
		}
	}
	return out
}

// methodName reads the HTTP method of a request call: http.MethodGet or "GET".
func methodName(e ast.Expr) string {
	switch v := e.(type) {
	case *ast.SelectorExpr:
		if strings.HasPrefix(v.Sel.Name, "Method") {
			return strings.ToUpper(strings.TrimPrefix(v.Sel.Name, "Method"))
		}
	case *ast.BasicLit:
		if v.Kind == token.STRING {
			if s, err := strconv.Unquote(v.Value); err == nil {
				return strings.ToUpper(s)
			}
		}
	}
	return ""
}

// pathName reads the route of a request call. An interpolated part becomes
// {name}, so the source's "/sync/user/"+uid lines up with the table's
// /sync/user/{uid}.
func pathName(e ast.Expr) string {
	switch v := e.(type) {
	case *ast.BasicLit:
		if v.Kind == token.STRING {
			if s, err := strconv.Unquote(v.Value); err == nil {
				return s
			}
		}
	case *ast.BinaryExpr:
		if v.Op == token.ADD {
			return pathName(v.X) + pathName(v.Y)
		}
	case *ast.Ident:
		return "{" + v.Name + "}"
	}
	return "{expr}"
}

// site is a place in the panel that reads a node response.
type site struct {
	file string // repo-relative
	fn   string // "" = the whole file
	base string // the variable holding the node response
}

// parseCitation reads "file.go:Func:base", "file.go:base" or "file.tsx".
func parseCitation(c string) (site, error) {
	parts := strings.Split(c, ":")
	switch len(parts) {
	case 1:
		return site{file: parts[0]}, nil
	case 2:
		return site{file: parts[0], base: parts[1]}, nil
	case 3:
		return site{file: parts[0], fn: parts[1], base: parts[2]}, nil
	}
	return site{}, fmt.Errorf("malformed citation %q", c)
}

// keyReads returns the keys the panel reads on the cited variable, with the
// line of each read.
func keyReads(t *testing.T, s site) map[string]int {
	t.Helper()
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, repoPath(s.file), nil, 0)
	if err != nil {
		t.Fatalf("parse %s: %v", s.file, err)
	}
	out := map[string]int{}
	found := false
	for _, decl := range f.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || fn.Body == nil {
			continue
		}
		if s.fn != "" && fn.Name.Name != s.fn {
			continue
		}
		found = true
		ast.Inspect(fn.Body, func(n ast.Node) bool {
			idx, ok := n.(*ast.IndexExpr)
			if !ok {
				return true
			}
			lit, ok := idx.Index.(*ast.BasicLit)
			if !ok || lit.Kind != token.STRING {
				return true
			}
			key, err := strconv.Unquote(lit.Value)
			if err != nil {
				return true
			}
			if !baseMatches(exprText(fset, idx.X), s.base) {
				return true
			}
			if _, seen := out[key]; !seen {
				out[key] = fset.Position(idx.Pos()).Line
			}
			return true
		})
	}
	if s.fn != "" && !found {
		t.Fatalf("the contract cites %s:%s, which is not a function in %s", s.file, s.fn, s.file)
	}
	return out
}

// exprText renders an expression, e.g. res.info.
func exprText(fset *token.FileSet, e ast.Expr) string {
	var buf bytes.Buffer
	if err := printer.Fprint(&buf, fset, e); err != nil {
		return ""
	}
	return buf.String()
}

// baseMatches reports whether a read base is the cited variable.
func baseMatches(base, cited string) bool {
	if cited == "" {
		return true
	}
	return base == cited || strings.HasSuffix(base, "."+cited)
}

// recorded is one request the panel sent to a node.
type recorded struct {
	method string
	path   string
	query  url.Values
	body   map[string]any
}

// recorder is a fake node that records what the panel sent it.
type recorder struct {
	mu   sync.Mutex
	seen []recorded
}

func (rec *recorder) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var body map[string]any
	if raw, err := io.ReadAll(r.Body); err == nil && len(raw) > 0 {
		_ = json.Unmarshal(raw, &body)
	}
	rec.mu.Lock()
	rec.seen = append(rec.seen, recorded{method: r.Method, path: r.URL.Path, query: r.URL.Query(), body: body})
	rec.mu.Unlock()
	if strings.HasPrefix(r.URL.Path, "/sync/download/ovpn/") {
		w.Header().Set("Content-Type", "application/x-openvpn-profile")
		_, _ = w.Write([]byte(contractProfile))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"success":true,"msg":"ok","data":{}}`))
}

// bodyPaths flattens a JSON body into the field paths the panel sent:
// "users", "users[].id".
func bodyPaths(prefix string, v any, out map[string]bool) {
	switch t := v.(type) {
	case map[string]any:
		for k, val := range t {
			p := k
			if prefix != "" {
				p = prefix + "." + k
			}
			out[p] = true
			bodyPaths(p, val, out)
		}
	case []any:
		for _, item := range t {
			bodyPaths(prefix+"[]", item, out)
		}
	}
}

// contractTable indexes the contract rows by route.
func contractTable(t *testing.T) map[route]node.ContractRow {
	t.Helper()
	out := map[route]node.ContractRow{}
	for _, row := range node.Contract {
		r := route{method: row.Method, path: row.Path}
		if _, dup := out[r]; dup {
			t.Fatalf("the contract table has two rows for %s", r)
		}
		out[r] = row
	}
	return out
}

// sortedKeys returns the sorted keys of a set.
func sortedKeys(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// sameStrings reports whether two sorted slices hold the same values.
func sameStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// TestNodeContractRoutes: the routes the panel's client can send and the
// contract table must be the same set, and every row must name the function
// that sends it.
func TestNodeContractRoutes(t *testing.T) {
	emitted := emittedRoutes(t)
	table := contractTable(t)

	for r, sites := range emitted {
		if _, ok := table[r]; !ok {
			t.Fatalf("the panel sends %s at %s:%d but the contract table has no row for it",
				r, sites[0].file, sites[0].line)
		}
	}
	for r, row := range table {
		sites, ok := emitted[r]
		if !ok {
			t.Fatalf("contract row %s is never sent by the panel's client", r)
		}
		file, fn, ok := strings.Cut(row.RequestAt, ":")
		if !ok {
			t.Fatalf("contract row %s has no RequestAt citation", r)
		}
		sent := false
		for _, s := range sites {
			if s.file == file && s.fn == fn {
				sent = true
			}
		}
		if !sent {
			t.Fatalf("contract row %s cites %s as the request site, but that function does not send it", r, row.RequestAt)
		}
	}
}

// TestNodeContractRequests: what the client sends must match the request
// fields the contract table lists.
func TestNodeContractRequests(t *testing.T) {
	rec := &recorder{}
	srv := httptest.NewTLSServer(rec)
	defer srv.Close()
	host, port := hostPort(t, srv.URL)
	c, err := node.NewClient(host, port, "api-key", certPEM(t, srv), "", 0)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}

	uid := "4242"
	maxLogins := 3
	dns1, dns2 := "1.1.1.1", "8.8.8.8"
	ipv6 := true
	prefix, extra := "2001:db8::/64", "1195,1196"
	drivers := []struct {
		name string
		call func(c *node.Client)
	}{
		{"CheckNode", func(c *node.Client) { c.CheckNode() }},
		{"GetNodeInfo", func(c *node.Client) { c.GetNodeInfo() }},
		{"GetUsage", func(c *node.Client) { c.GetUsage(0) }},
		{"UpdateConfig", func(c *node.Client) {
			c.UpdateConfig(node.UpdateConfigParams{
				TunnelAddress: "10.8.0.1", Protocol: "tcp", OVPNPort: 1194,
				DNS1: &dns1, DNS2: &dns2, EnableIPv6: &ipv6, IPv6Prefix: &prefix, ExtraPorts: &extra,
			})
		}},
		{"RestartVPN", func(c *node.Client) { c.RestartVPN() }},
		{"RenewServerCert", func(c *node.Client) { c.RenewServerCert() }},
		{"TriggerUpdate", func(c *node.Client) { c.TriggerUpdate() }},
		{"CreateUser", func(c *node.Client) { c.CreateUser("amy", maxLogins, uid) }},
		{"DeleteUser", func(c *node.Client) { c.DeleteUser(uid) }},
		{"DisconnectUser", func(c *node.Client) { c.DisconnectUser(uid, true, 0) }},
		{"ResetUsage", func(c *node.Client) { c.ResetUsage(uid) }},
		{"GetSessions", func(c *node.Client) { c.GetSessions("amy", 8, 0) }},
		{"GetLogs", func(c *node.Client) { c.GetLogs("ERROR", 10) }},
		{"DownloadOVPNBytes", func(c *node.Client) { c.DownloadOVPNBytes(uid) }},
	}
	for _, d := range drivers {
		d.call(c)
	}
	if got := c.DownloadOVPNBytes(uid); len(got) == 0 {
		t.Fatalf("the .ovpn download returned nothing: the panel did not take the body as raw text")
	}

	// The bulk limit push is the one route that needs a database.
	conn := newNodeDB(t)
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca)
		 VALUES (1, 'n1', ?, '', 'tcp', 1194, ?, 'k', 1, ?)`,
		host, port, certPEM(t, srv)); err != nil {
		t.Fatalf("insert node: %v", err)
	}
	if _, err := conn.Exec(
		`INSERT INTO users (id, uuid, name, total, used, max_logins, is_active) VALUES (1, 'u-1', 'amy', 0, 0, 2, 1)`,
	); err != nil {
		t.Fatalf("insert user: %v", err)
	}
	node.SyncAllUserLimits(conn)

	table := contractTable(t)
	seen := map[route]bool{}
	for _, req := range rec.seen {
		r := route{method: req.method, path: strings.ReplaceAll(req.path, uid, "{uid}")}
		row, ok := table[r]
		if !ok {
			t.Fatalf("the panel sent %s, which the contract table does not describe", r)
		}
		seen[r] = true

		gotQuery := make([]string, 0, len(req.query))
		for k := range req.query {
			gotQuery = append(gotQuery, k)
		}
		sort.Strings(gotQuery)
		wantQuery := append([]string{}, row.Query...)
		sort.Strings(wantQuery)
		if !sameStrings(gotQuery, wantQuery) {
			t.Fatalf("%s sends query %v, the contract table lists %v", r, gotQuery, wantQuery)
		}

		gotBody := map[string]bool{}
		bodyPaths("", req.body, gotBody)
		wantBody := map[string]bool{}
		for _, f := range row.Request {
			wantBody[f] = true
		}
		if !sameStrings(sortedKeys(gotBody), sortedKeys(wantBody)) {
			t.Fatalf("%s sends body fields %v, the contract table lists %v",
				r, sortedKeys(gotBody), sortedKeys(wantBody))
		}
	}
	for r := range table {
		if !seen[r] {
			t.Fatalf("contract row %s is never sent by the panel's client", r)
		}
	}
}

// TestNodeContractResponses: the keys the panel reads from a node response
// must be exactly the keys the contract row lists.
func TestNodeContractResponses(t *testing.T) {
	for _, row := range node.Contract {
		listed := map[string]bool{}
		for _, k := range row.Response {
			listed[k] = true
		}
		for _, k := range row.ResponseItems {
			listed[k] = true
		}
		found := map[string]bool{}
		for _, citation := range row.ResponseAt {
			s, err := parseCitation(citation)
			if err != nil {
				t.Fatalf("contract row %s %s has a malformed citation %q", row.Method, row.Path, citation)
			}
			if strings.HasSuffix(s.file, ".tsx") {
				// The SPA reads the payload in this file.
				content, err := os.ReadFile(repoPath(s.file))
				if err != nil {
					t.Fatalf("read %s: %v", s.file, err)
				}
				for k := range listed {
					if strings.Contains(string(content), "."+k) {
						found[k] = true
					}
				}
				continue
			}
			for k, line := range keyReads(t, s) {
				if !listed[k] {
					t.Fatalf("the panel reads key %q from %s %s at %s:%d, but the contract row does not list it",
						k, row.Method, row.Path, s.file, line)
				}
				found[k] = true
			}
		}
		for _, k := range row.Response {
			if !found[k] {
				t.Fatalf("contract row %s %s lists key %q, but no cited panel code reads it",
					row.Method, row.Path, k)
			}
		}
		for _, k := range row.ResponseItems {
			if !found[k] {
				t.Fatalf("contract row %s %s lists item key %q, but no cited panel code reads it",
					row.Method, row.Path, k)
			}
		}
	}
}

// TestNodeContractOVPNRaw: the .ovpn download is raw text, and the panel
// rewrites it as text.
func TestNodeContractOVPNRaw(t *testing.T) {
	row, ok := findContractRow(t, http.MethodGet, "/sync/download/ovpn/{uid}")
	if !ok {
		t.Fatalf("the contract table has no row for GET /sync/download/ovpn/{uid}")
	}
	if !row.ResponseRaw {
		t.Fatalf("the .ovpn download row must be marked raw: the body is a profile, not an envelope")
	}
	for _, r := range node.Contract {
		if r.ResponseRaw && r.Path != row.Path {
			t.Fatalf("only the .ovpn download is raw, but %s %s is marked raw too", r.Method, r.Path)
		}
	}

	rec := &recorder{}
	srv := httptest.NewTLSServer(rec)
	defer srv.Close()
	host, port := hostPort(t, srv.URL)
	conn := newNodeDB(t)
	if _, err := conn.Exec(`INSERT INTO settings (id, panel_id, panel_domain) VALUES (1, 'pid', 'panel.example.com')`); err != nil {
		t.Fatalf("settings: %v", err)
	}
	if _, err := conn.Exec(
		`INSERT INTO nodes (id, name, address, tunnel_address, protocol, ovpn_port, port, key, status, server_ca)
		 VALUES (1, 'n1', ?, '', 'tcp', 1194, ?, 'k', 1, ?)`,
		host, port, certPEM(t, srv)); err != nil {
		t.Fatalf("insert node: %v", err)
	}
	out := node.DownloadOVPNClient(7, 1, conn)
	if out == nil {
		t.Fatalf("DownloadOVPNClient = nil, want the raw profile")
	}
	text := string(out)
	if !strings.Contains(text, "<ca>") {
		t.Fatalf("the profile body was not passed through as text:\n%s", text)
	}
	if !strings.Contains(text, "remote panel.example.com 1194") {
		t.Fatalf("the remote lines were not rewritten as text:\n%s", text)
	}
}

// findContractRow returns the contract row for a method and path.
func findContractRow(t *testing.T, method, path string) (node.ContractRow, bool) {
	t.Helper()
	for _, row := range node.Contract {
		if row.Method == method && row.Path == path {
			return row, true
		}
	}
	return node.ContractRow{}, false
}
