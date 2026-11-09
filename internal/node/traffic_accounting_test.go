package node

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

// accountingServer serves a mutable /sync/usage payload so one test can run
// several SyncTraffic passes against the same node.
type accountingServer struct {
	mu      sync.Mutex
	totals  map[string]any
	epochs  map[string]string
	hasEpoc bool
}

func (s *accountingServer) set(totals map[string]any, epochs map[string]string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.totals = totals
	s.epochs = epochs
	s.hasEpoc = epochs != nil
}

func (s *accountingServer) handler(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	data := map[string]any{"totals": s.totals}
	if s.hasEpoc {
		ep := map[string]any{}
		for k, v := range s.epochs {
			ep[k] = v
		}
		data["totals_epochs"] = ep
	}
	w.Header().Set("Content-Type", "application/json")
	body, _ := json.Marshal(map[string]any{"success": true, "data": data})
	_, _ = w.Write(body)
}

func newAccountingServer(t *testing.T) (*accountingServer, *httptest.Server) {
	t.Helper()
	s := &accountingServer{}
	srv := httptest.NewTLSServer(http.HandlerFunc(s.handler))
	t.Cleanup(srv.Close)
	return s, srv
}

// TestEpochAggregationIsOrderIndependent: opposite aggregate epoch orders
// must produce the same stored epoch (no reseed of unchanged counters).
func TestEpochAggregationIsOrderIndependent(t *testing.T) {
	group := "10=1793900000000000000-1,20=1793900000000000000-2"
	scalar := "1793900000000000000-3"
	forward := aggregateEpoch(group, scalar)
	reverse := aggregateEpoch(scalar, group)
	if forward != reverse {
		t.Fatalf("unchanged epoch contributors depend on map iteration order: %q != %q", forward, reverse)
	}
}

// TestReservedLookingUsernameIsBilled: a reported username "push_hash" is a
// real user; reserved keys exist only in stored bookkeeping.
func TestReservedLookingUsernameIsBilled(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	seedTrafficNode(t, conn, 1, "node", usageServer(t, map[string]any{"1": int64(100)}, 0))
	seedTrafficUser(t, conn, 1, "push_hash", "0", `{"1":0}`)
	result := SyncTraffic(conn)
	if result.BytesBilled != 100 {
		t.Fatalf("valid legacy username push_hash was skipped: billed=%d, want 100", result.BytesBilled)
	}
	if got := userUsed(t, conn, 1); got != 100 {
		t.Fatalf("used=%d, want 100", got)
	}
}

// TestSyncTrafficEpochDecreaseReboundAndReset drives the held-baseline and
// explicit-reset rules through real SyncTraffic passes.
func TestSyncTrafficEpochDecreaseReboundAndReset(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "alice", "0", `{}`)

	pass := func(total int64, epoch string) int64 {
		srv.set(map[string]any{"1": total}, map[string]string{"1": epoch})
		return SyncTraffic(conn).BytesBilled
	}
	if got := pass(120, "e1"); got != 0 {
		t.Fatalf("first poll seeded: billed=%d, want 0", got)
	}
	if got := pass(100, "e1"); got != 0 {
		t.Fatalf("unexplained decrease billed=%d, want 0", got)
	}
	if got := pass(120, "e1"); got != 0 {
		t.Fatalf("rebound to held baseline billed=%d, want 0", got)
	}
	if got := pass(130, "e1"); got != 10 {
		t.Fatalf("increase past held baseline billed=%d, want 10", got)
	}
	if got := pass(500, "e2"); got != 0 {
		t.Fatalf("epoch change seeded: billed=%d, want 0", got)
	}
	if got := pass(510, "e2"); got != 10 {
		t.Fatalf("post-reset increase billed=%d, want 10", got)
	}
	if got := userUsed(t, conn, 1); got != 20 {
		t.Fatalf("used=%d, want 20", got)
	}
	state := userState(t, conn, 1)
	if ep, ok := state[EpochsKey].(map[string]any); !ok || ep["1"] != "e2" {
		t.Fatalf("stored epochs=%v, want node 1 at e2", state[EpochsKey])
	}
}

// TestSyncTrafficFirstEpochAdoption: legacy passes without epochs seed a
// baseline; the first epoch then adopts without re-billing the seed.
func TestSyncTrafficFirstEpochAdoption(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":100}`)

	srv.set(map[string]any{"1": int64(120)}, nil) // legacy: no epochs
	if got := SyncTraffic(conn).BytesBilled; got != 20 {
		t.Fatalf("legacy delta billed=%d, want 20", got)
	}
	srv.set(map[string]any{"1": int64(130)}, map[string]string{"1": "e1"})
	if got := SyncTraffic(conn).BytesBilled; got != 10 {
		t.Fatalf("first epoch adoption billed=%d, want 10 (not a reseed)", got)
	}
	state := userState(t, conn, 1)
	if ep, ok := state[EpochsKey].(map[string]any); !ok || ep["1"] != "e1" {
		t.Fatalf("stored epochs=%v, want adopted e1", state[EpochsKey])
	}
}

// TestSyncTrafficIntegerPrecisionAbove2^53: a one-byte increase above 2^53
// bills exactly one byte (no float conversion).
func TestSyncTrafficIntegerPrecisionAbove2_53(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	const base = int64(9007199254740992) // 2^53
	seedTrafficUser(t, conn, 1, "alice", "0", `{"1":9007199254740992}`)
	srv.set(map[string]any{"1": base + 1}, map[string]string{"1": "e1"})
	if got := SyncTraffic(conn).BytesBilled; got != 1 {
		t.Fatalf("billed=%d, want exactly 1 above 2^53", got)
	}
	if got := userUsed(t, conn, 1); got != 1 {
		t.Fatalf("used=%d, want 1", got)
	}
}

// TestSyncTrafficInvalidTotalsDoNotMutate: negative, fractional, oversized,
// and malformed node totals are skipped without touching usage/baselines.
func TestSyncTrafficInvalidTotalsDoNotMutate(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "alice", "40", `{"1":100,"__epochs":{"1":"e1"}}`)

	invalid := []map[string]any{
		{"1": int64(-5)},
		{"1": json.Number("1.5")},
		{"1": json.Number("99999999999999999999999")},
		{"1": "not-a-number"},
	}
	for i, totals := range invalid {
		srv.set(totals, map[string]string{"1": "e1"})
		res := SyncTraffic(conn)
		if res.BytesBilled != 0 {
			t.Fatalf("case %d billed=%d on invalid total %v", i, res.BytesBilled, totals)
		}
		if got := userUsed(t, conn, 1); got != 40 {
			t.Fatalf("case %d mutated used to %d", i, got)
		}
		state := userState(t, conn, 1)
		if b, ok := state["1"].(json.Number); !ok || b.String() != "100" {
			// node_usage may store the baseline as json.Number or float-free int form
			if f, ok := state["1"].(float64); !ok || f != 100 {
				t.Fatalf("case %d mutated baseline: %v", i, state["1"])
			}
		}
	}
	// A valid increase afterwards still bills against the untouched baseline.
	srv.set(map[string]any{"1": int64(110)}, map[string]string{"1": "e1"})
	if got := SyncTraffic(conn).BytesBilled; got != 10 {
		t.Fatalf("valid increase after invalid samples billed=%d, want 10", got)
	}
}

// TestSyncTrafficReseedInvalidatesOfflineEpochs: a reseed marker drops
// baselines and epochs for nodes that did not answer this pass.
func TestSyncTrafficReseedInvalidatesOfflineEpochs(t *testing.T) {
	resetForTests()
	t.Cleanup(resetForTests)
	conn := newTrafficDB(t)
	srv, httpSrv := newAccountingServer(t)
	seedTrafficNode(t, conn, 1, "node", httpSrv)
	seedTrafficUser(t, conn, 1, "alice", "0",
		`{"1":999,"2":888,"__reseed":true,"__epochs":{"1":"e1","2":"e9"}}`)
	srv.set(map[string]any{"1": int64(50)}, map[string]string{"1": "e2"})
	if got := SyncTraffic(conn).BytesBilled; got != 0 {
		t.Fatalf("reseed pass billed=%d, want 0", got)
	}
	state := userState(t, conn, 1)
	if _, ok := state["2"]; ok {
		t.Fatalf("offline node baseline survived reseed: %v", state)
	}
	ep, ok := state[EpochsKey].(map[string]any)
	if !ok {
		t.Fatalf("epochs missing after reseed: %v", state)
	}
	if _, ok := ep["2"]; ok {
		t.Fatalf("offline node epoch survived reseed: %v", ep)
	}
	if ep["1"] != "e2" {
		t.Fatalf("answered node epoch=%v, want e2", ep["1"])
	}
	if _, ok := state[ReseedMarkerKey]; ok {
		t.Fatal("reseed marker was not consumed")
	}
}
