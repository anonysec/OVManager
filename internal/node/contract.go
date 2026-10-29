package node

import "net/http"

// The panel↔node contract: every node endpoint the panel calls, the request
// fields it sends and the response keys it reads.
//
// The panel is the client of the node agent's /sync API, but those
// expectations were spread thin over client.go, sync.go, management.go,
// diagnostics.go, traffic.go and panel/security.go — thin enough that a
// node-side change the panel cannot absorb only surfaced as an empty field
// in the SPA. This table is the one place that says what the node has to
// answer; test/node_contract_test.go keeps it and the code in step.
//
// A citation is "file.go:Func:var" (the node response arrives in var inside
// Func), "file.go:var" (the same, anywhere in the file) or "file.tsx" (the
// SPA file that reads the route's payload). The test checks the function,
// never a line number: a line number moves with every edit above it. The
// line numbers in the comments are the current ones.
//
// The node also serves GET /sync/config, PUT /sync/users/{cn} and
// PUT /sync/pki. The panel calls none of them, so they are not part of what
// this panel asks of a node.
type ContractRow struct {
	// Method and Path are the HTTP method and the node route; {uid} marks
	// the interpolated path parameter.
	Method string
	Path   string
	// Query lists the query parameters the panel sends.
	Query []string
	// Request lists the JSON body fields the panel sends. "users[].id" is a
	// field of one item of the "users" list.
	Request []string
	// Response lists the data keys the panel reads from the response.
	Response []string
	// ResponseItems lists the keys the panel reads inside one list item: a
	// live_sessions entry, an events entry, a log record.
	ResponseItems []string
	// ResponseRaw marks a body that is not the {success,msg,data} envelope.
	ResponseRaw bool
	// RequestAt is where the panel builds the request: "file.go:Func".
	RequestAt string
	// ResponseAt is where the panel consumes the response.
	ResponseAt []string
	// Note records what a reader must know: a key the node sends that the
	// panel never reads, or a route the panel never calls.
	Note string
}

// Contract is what the panel asks of a node agent: one row per call.
var Contract = []ContractRow{
	{
		// Reachability probe and status read (client.go:516, client.go:521).
		Method:    http.MethodGet,
		Path:      "/sync/status",
		RequestAt: "internal/node/client.go:GetNodeInfo",
		Response:  []string{"version", "cpu_usage", "memory_usage", "cert_expiry"},
		ResponseAt: []string{
			"internal/node/management.go:info",   // version (management.go:301)
			"internal/telemetry/handler.go:info", // cpu_usage, memory_usage (handler.go:459)
			"web/src/components/NodeDrawer.tsx",  // cert_expiry (NodeDrawer.tsx:136)
		},
		Note: "the panel ignores every other key of this payload: " +
			"openvpn_running is read from the restart response, not from here",
	},
	{
		// Per-user traffic counters (client.go:529).
		Method:    http.MethodGet,
		Path:      "/sync/usage",
		RequestAt: "internal/node/client.go:GetUsage",
		Response:  []string{"totals"},
		ResponseAt: []string{
			"internal/node/traffic.go:data", // totals (traffic.go:82)
		},
		Note: "totals may be null when the node has no user to report (traffic.go:84)",
	},
	{
		// Live sessions, stale markers and the login-health counters.
		Method:    http.MethodGet,
		Path:      "/sync/sessions",
		Query:     []string{"hours", "common_name"},
		RequestAt: "internal/node/client.go:GetSessions",
		Response: []string{
			"live_sessions", "stale_markers", "live_count", "stale_marker_count",
			"auth_errors", "auth_errors_by_cn", "rejects", "policy_rejects",
			"warn_rejects", "events", "last_error",
		},
		ResponseItems: []string{
			"common_name",                                                 // a live_sessions or stale_markers entry
			"cn", "peer", "ts", "action", "severity", "reason", "ongoing", // an events entry
		},
		ResponseAt: []string{
			"internal/node/diagnostics.go:data",            // live_sessions, stale_markers, auth_errors, auth_errors_by_cn, live_count, stale_marker_count (diagnostics.go:81)
			"internal/node/diagnostics.go:s",               // common_name (diagnostics.go:112)
			"internal/node/sync.go:cleanNodeSessions:data", // live_sessions, stale_markers (sync.go:286)
			"internal/panel/security.go:data",              // rejects, policy_rejects, warn_rejects, last_error, events (security.go:297)
			"internal/panel/security.go:nodeEvents:ev",     // cn, peer, ts, action, severity, reason, ongoing (security.go:178)
			"internal/telemetry/handler.go:sessions",       // live_count, auth_errors, rejects, stale_marker_count (handler.go:460)
			"internal/telemetry/handler.go:data",           // live_sessions (handler.go:585)
		},
		Note: "common_name is only sent when the panel asks for one user; " +
			"the SPA also accepts a legacy sessions key (NodeDrawer.tsx:129)",
	},
	{
		// The node's log ring (client.go:681).
		Method:    http.MethodGet,
		Path:      "/sync/logs",
		Query:     []string{"level", "limit"},
		RequestAt: "internal/node/client.go:GetLogs",
		Response:  []string{"records", "last_error", "errors_1h"},
		ResponseItems: []string{
			"level", "time", "message", "where", // a log record
		},
		ResponseAt: []string{
			"web/src/components/NodeDrawer.tsx", // records, last_error, errors_1h (NodeDrawer.tsx:500)
		},
		Note: "the Go panel forwards the payload unread (management.go:971); the SPA reads it",
	},
	{
		// The endpoint settings: tunnel address, protocol, port, DNS, IPv6.
		Method:    http.MethodPost,
		Path:      "/sync/config",
		RequestAt: "internal/node/client.go:UpdateConfig",
		Request: []string{
			"tunnel_address", "protocol", "ovpn_port", "set_new_setting",
			"dns1", "dns2", "enable_ipv6", "ipv6_prefix", "extra_ports",
		},
		Note: "the panel reads the envelope only (success, msg); the node's data " +
			"is forwarded to the SPA unread (management.go:1061)",
	},
	{
		// Restart OpenVPN (client.go:582).
		Method:    http.MethodPost,
		Path:      "/sync/restart",
		RequestAt: "internal/node/client.go:RestartVPN",
		Response:  []string{"openvpn_running"},
		ResponseAt: []string{
			"web/src/components/NodeDrawer.tsx", // openvpn_running (NodeDrawer.tsx:175)
		},
		Note: "the Go panel forwards the envelope's data unread (management.go:1085)",
	},
	{
		// Renew the node's server certificate (client.go:587).
		Method:    http.MethodPost,
		Path:      "/sync/renew-cert",
		RequestAt: "internal/node/client.go:RenewServerCert",
		Response:  []string{"server_expiry"},
		ResponseAt: []string{
			"web/src/components/NodeDrawer.tsx", // server_expiry (NodeDrawer.tsx:185)
		},
		Note: "the Go panel forwards the envelope's data unread (management.go:1085)",
	},
	{
		// The node's self-update (client.go:592).
		Method:    http.MethodPost,
		Path:      "/sync/update",
		RequestAt: "internal/node/client.go:TriggerUpdate",
		Note:      "the panel reads the envelope only (success, msg)",
	},
	{
		// Delete a user (client.go:623).
		Method:    http.MethodDelete,
		Path:      "/sync/user/{uid}",
		RequestAt: "internal/node/client.go:DeleteUser",
		Note:      "no data key is read: the client only checks the envelope",
	},
	{
		// Drop a user's sessions (client.go:641).
		Method:    http.MethodPost,
		Path:      "/sync/user/{uid}/disconnect",
		Query:     []string{"only_stale"},
		RequestAt: "internal/node/client.go:DisconnectUser",
		Response:  []string{"removed_markers", "killed_sessions"},
		ResponseAt: []string{
			"internal/node/sync.go:cleanNodeSessions:res", // removed_markers (sync.go:305)
			"internal/users/sweep.go:res",                 // killed_sessions (sweep.go:183)
		},
		Note: "only_stale is sent only when the panel asks the node to drop " +
			"stale markers instead of live sessions (client.go:638)",
	},
	{
		// The .ovpn profile itself: raw text, not an envelope.
		Method:      http.MethodGet,
		Path:        "/sync/download/ovpn/{uid}",
		RequestAt:   "internal/node/client.go:DownloadOVPNBytes",
		ResponseRaw: true,
		Note: "the panel accepts a body that starts with \"client\" or holds " +
			"\"<ca>\" (client.go:770) and rewrites the remote lines as text " +
			"(management.go:569)",
	},
	{
		// The bulk max-logins push (sync.go:100).
		Method:    http.MethodPost,
		Path:      "/sync/users",
		RequestAt: "internal/node/sync.go:pushLimitsBatch",
		Request:   []string{"users", "users[].id", "users[].max_logins"},
		Response:  []string{"applied", "failed"},
		ResponseAt: []string{
			"internal/node/sync.go:pushLimitsBatch:data", // applied, failed (sync.go:109)
		},
	},
}
