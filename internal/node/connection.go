// Per-node connection registry with health tracking (backend/node/connection.py).
package node

import (
	"sync"
	"time"
)

// NodeHealth is the explicit connection state machine.
type NodeHealth string

// Health states.
const (
	HealthUnknown NodeHealth = "unknown"
	HealthHealthy NodeHealth = "healthy"
	HealthBroken  NodeHealth = "broken"
)

// ConnectionSignature fields, when changed, require a new transport.
type ConnectionSignature struct {
	Address  string
	Port     int
	APIKey   string
	ServerCA string
}

func signatureOf(n *Node) ConnectionSignature {
	return ConnectionSignature{
		Address:  n.Address,
		Port:     n.Port,
		APIKey:   n.Key,
		ServerCA: n.ServerCA.String,
	}
}

type connection struct {
	client    *Client
	signature ConnectionSignature
	health    NodeHealth
	lastOK    time.Time
	lastFail  time.Time
}

const healthTTL = 300 * time.Second

// BrokenProbeTimeout is the short timeout used to re-probe a broken node.
const BrokenProbeTimeout = 3 * time.Second

var (
	connMu      sync.Mutex
	connections = map[int64]*connection{}
)

// NodeClient returns a live client for node, reusing the cached connection
// when the signature is unchanged (backend/node/requests.node_client +
// connection.get_connection). panelID stamps X-Panel-ID.
func NodeClient(n *Node, panelID string) *Client {
	c := getConnection(n)
	if panelID != "" && c != nil {
		c.Headers()["X-Panel-ID"] = panelID
	}
	return c
}

// Headers exposes the mutable header map (the node_client panel-id stamp).
func (c *Client) Headers() map[string]string { return c.headers }

func getConnection(n *Node) *Client {
	sig := signatureOf(n)
	if n.ID == 0 {
		c, err := NewClient(sig.Address, sig.Port, sig.APIKey, sig.ServerCA, "", 0)
		if err != nil {
			return nil
		}
		return c
	}
	connMu.Lock()
	if conn, ok := connections[n.ID]; ok && conn.signature == sig {
		c := conn.client
		connMu.Unlock()
		return c
	}
	connMu.Unlock()

	c, err := NewClient(sig.Address, sig.Port, sig.APIKey, sig.ServerCA, "", n.ID)
	if err != nil {
		return nil
	}
	connMu.Lock()
	defer connMu.Unlock()
	if conn, ok := connections[n.ID]; ok && conn.signature == sig {
		return conn.client
	}
	connections[n.ID] = &connection{client: c, signature: sig, health: HealthUnknown}
	return c
}

// Record stores an RPC outcome by node id (only for cached connections).
func Record(nodeID int64, ok bool) {
	if nodeID == 0 {
		return
	}
	connMu.Lock()
	defer connMu.Unlock()
	conn, found := connections[nodeID]
	if !found {
		return
	}
	if ok {
		conn.health = HealthHealthy
		conn.lastOK = time.Now()
	} else {
		conn.health = HealthBroken
		conn.lastFail = time.Now()
	}
}

// Healthy is the cheap health check honoring the TTL (True while UNKNOWN).
func Healthy(n *Node) bool {
	if n.ID == 0 {
		return true
	}
	connMu.Lock()
	defer connMu.Unlock()
	conn, found := connections[n.ID]
	if !found {
		return true
	}
	if conn.health == HealthBroken {
		return false
	}
	if conn.health == HealthHealthy && time.Since(conn.lastOK) <= healthTTL {
		return true
	}
	return true
}

// ProbeTimeout is the timeout to use when periodically probing this node.
func ProbeTimeout(n *Node) time.Duration {
	if Healthy(n) {
		return LongTimeout
	}
	return BrokenProbeTimeout
}

// Forget drops a node's connection entry (node deleted).
func Forget(nodeID int64) {
	connMu.Lock()
	defer connMu.Unlock()
	delete(connections, nodeID)
}

// ResetForTests clears the registry and health state.
func ResetForTests() {
	connMu.Lock()
	defer connMu.Unlock()
	connections = map[int64]*connection{}
}
