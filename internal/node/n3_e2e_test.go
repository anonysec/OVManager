package node

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/anonysec/OVManager/go/internal/auth"
	_ "modernc.org/sqlite"
)

func TestFingerprintConfirmationFlowEndToEnd(t *testing.T) {
	d := setupNodeTestDB(t)
	dir := t.TempDir()
	svc := auth.NewService(d, dir)
	h := NewHandler(svc)

	cert := generateTestCert(t, "node-cert")
	fp := CertFingerprint(cert)
	wrongFP := "00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff"

	// --- node test path ---
	testBody := func(extra string) string {
		return `{"address":"127.0.0.1","port":1,"key":"secret-api-key","cert":"` + strings.ReplaceAll(cert, "\n", "\\n") + `"` + extra + `}`
	}

	// 1. No fingerprint: must require confirmation and expose fingerprint.
	w1 := httptest.NewRecorder()
	h.handleTestNode(w1, httptest.NewRequest(http.MethodPost, "/nodes/test", strings.NewReader(testBody(""))))
	var r1 map[string]any
	_ = json.Unmarshal(w1.Body.Bytes(), &r1)
	data1, _ := r1["data"].(map[string]any)
	if data1["confirmation_required"] != true {
		t.Fatalf("test: expected confirmation_required, got %v", r1)
	}
	if data1["fingerprint"] != fp {
		t.Fatalf("test: fingerprint = %v, want %s", data1["fingerprint"], fp)
	}

	// 2. Wrong fingerprint: must be rejected.
	w2 := httptest.NewRecorder()
	h.handleTestNode(w2, httptest.NewRequest(http.MethodPost, "/nodes/test", strings.NewReader(testBody(`,"expected_fingerprint":"`+wrongFP+`"`))))
	var r2 map[string]any
	_ = json.Unmarshal(w2.Body.Bytes(), &r2)
	if r2["success"] == true {
		t.Fatal("test: wrong fingerprint unexpectedly succeeded")
	}
	if !strings.Contains(r2["msg"].(string), "mismatch") {
		t.Fatalf("test: expected mismatch, got %v", r2["msg"])
	}

	// 3. Exact fingerprint: passes the gate (node unreachable is acceptable).
	w3 := httptest.NewRecorder()
	h.handleTestNode(w3, httptest.NewRequest(http.MethodPost, "/nodes/test", strings.NewReader(testBody(`,"expected_fingerprint":"`+fp+`"`))))
	var r3 map[string]any
	_ = json.Unmarshal(w3.Body.Bytes(), &r3)
	if cr, _ := r3["data"].(map[string]any); cr != nil && cr["confirmation_required"] == true {
		t.Fatalf("test: exact fingerprint still requires confirmation")
	}

	// --- node add path ---
	addReq := func(extra string) nodeCreate {
		key := "secret-api-key"
		c := cert
		req := nodeCreate{Name: "n1", Address: "127.0.0.1", Port: 1, Key: &key, Cert: &c}
		if extra != "" {
			ef := fp
			if extra == "wrong" {
				ef = wrongFP
			}
			req.ExpectedFingerprint = &ef
		}
		return req
	}

	ok, msg := AddNodeHandler(addReq(""), d)
	if ok || !strings.Contains(msg, "confirmation required") {
		t.Fatalf("add: unconfirmed result = %v %q", ok, msg)
	}
	ok, msg = AddNodeHandler(addReq("wrong"), d)
	if ok || !strings.Contains(msg, "mismatch") {
		t.Fatalf("add: wrong fingerprint result = %v %q", ok, msg)
	}
	ok, msg = AddNodeHandler(addReq("right"), d)
	// Node is unreachable, so success is false, but it must not be a fingerprint gate failure.
	if strings.Contains(msg, "confirmation required") || strings.Contains(msg, "mismatch") {
		t.Fatalf("add: exact fingerprint still gated: %q", msg)
	}
	_ = ok

	// --- re-pin path ---
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}))
	defer srv.Close()
	hostPort := srv.Listener.Addr().String()
	addr := "127.0.0.1"
	port, _ := strconv.Atoi(strings.SplitN(hostPort, ":", 2)[1])

	oldCert := generateTestCert(t, "old-node")
	oldFP := CertFingerprint(oldCert)
	res, err := d.Exec(`INSERT INTO nodes (name, address, port, ovpn_port, server_ca, key, status) VALUES ('rn', ?, ?, 1194, ?, 'k', 1)`, addr, port, oldCert)
	if err != nil {
		t.Fatal(err)
	}
	nodeID, _ := res.LastInsertId()
	_ = nodeID

	// 1. unconfirmed -> confirmation_required with old/new
	rr1 := httptest.NewRecorder()
	req1 := httptest.NewRequest(http.MethodPost, "/nodes/1/repin", strings.NewReader(`{}`))
	req1.SetPathValue("node_id", "1")
	h.handleRepin(rr1, req1)

	// The inserted id is likely 1 because table empty.
	var rep1 map[string]any
	_ = json.Unmarshal(rr1.Body.Bytes(), &rep1)
	repData1, _ := rep1["data"].(map[string]any)
	if repData1["confirmation_required"] != true {
		t.Fatalf("repin: expected confirmation_required, got %v", rep1)
	}
	if repData1["old_fingerprint"] != oldFP {
		t.Fatalf("repin: old fingerprint = %v, want %s", repData1["old_fingerprint"], oldFP)
	}
	newFP := repData1["new_fingerprint"].(string)
	if newFP == "" {
		t.Fatal("repin: missing new fingerprint")
	}

	// 2. wrong fingerprint -> mismatch
	rr2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodPost, "/nodes/1/repin", strings.NewReader(`{"expected_fingerprint":"`+wrongFP+`"}`))
	req2.SetPathValue("node_id", "1")
	h.handleRepin(rr2, req2)
	var rep2 map[string]any
	_ = json.Unmarshal(rr2.Body.Bytes(), &rep2)
	if rep2["success"] == true {
		t.Fatal("repin: wrong fingerprint succeeded")
	}
	if !strings.Contains(rep2["msg"].(string), "mismatch") && !strings.Contains(rep2["msg"].(string), "Mismatch") {
		t.Fatalf("repin: expected mismatch, got %v", rep2["msg"])
	}

	// 3. exact new fingerprint -> success and DB updated
	rr3 := httptest.NewRecorder()
	req3 := httptest.NewRequest(http.MethodPost, "/nodes/1/repin", strings.NewReader(`{"expected_fingerprint":"`+newFP+`"}`))
	req3.SetPathValue("node_id", "1")
	h.handleRepin(rr3, req3)
	var rep3 map[string]any
	_ = json.Unmarshal(rr3.Body.Bytes(), &rep3)
	if rep3["success"] != true {
		t.Fatalf("repin: exact fingerprint failed: %v", rep3)
	}
	var updatedCert string
	_ = d.QueryRow(`SELECT server_ca FROM nodes WHERE id = ?`, nodeID).Scan(&updatedCert)
	if CertFingerprint(updatedCert) != newFP {
		t.Fatalf("repin: DB fingerprint = %s, want %s", CertFingerprint(updatedCert), newFP)
	}
}
