package node

import (
	"database/sql"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"testing"
)

func defect2HostPort(t *testing.T, raw string) (string, int) {
	t.Helper()
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(u.Port())
	if err != nil {
		t.Fatal(err)
	}
	return u.Hostname(), port
}

func defect2CertPEM(t *testing.T, srv *httptest.Server) string {
	t.Helper()
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw}))
}

func TestTLSVerifiedResetsOnFailedPinnedRequest(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"msg":"ok","data":{}}`))
	}))
	defer srv.Close()
	host, port := defect2HostPort(t, srv.URL)

	c, err := NewClient(host, port, "api-key", defect2CertPEM(t, srv), "", 1)
	if err != nil {
		t.Fatal(err)
	}
	if !c.CheckNode() {
		t.Fatal("first pinned request should succeed")
	}
	if v := c.TLSVerified(); v == nil || !*v {
		t.Fatalf("TLSVerified after success = %v, want true", v)
	}

	// Force a failure on the same pinned client.
	srv.Close()
	c.CheckNode()
	v := c.TLSVerified()
	if v == nil || *v {
		t.Fatalf("TLSVerified after failed pinned request = %v, want false", v)
	}
}

func TestRecordTLSUnverifiedFiresOncePerNode(t *testing.T) {
	nodeID := int64(999999)
	unverifiedNodesMu.Lock()
	delete(unverifiedNodes, nodeID)
	unverifiedNodesMu.Unlock()

	calls := 0
	origAudit := AuditDB
	t.Cleanup(func() { AuditDB = origAudit })

	AuditDB = func() *sql.DB {
		calls++
		return nil
	}

	c := &Client{NodeID: nodeID, address: "1.2.3.4:2083"}
	c.recordTLSUnverified()
	if calls != 1 {
		t.Fatalf("expected AuditDB to be called once, got %d", calls)
	}

	// Second call for the same node must be suppressed
	c.recordTLSUnverified()
	if calls != 1 {
		t.Fatalf("expected AuditDB to remain 1 after second call, got %d", calls)
	}
}
