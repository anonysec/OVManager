# Review F — OVManager Go backend read-only audit
Scope: internal/**, test/** (web skipped). Read-only; no edits.
Known findings NOT re-reported: MountSub no-auth, CollectMetrics unchecked asserts, no CSRF Origin check, global node key, InsecureSkipVerify fallback, numeric-usage-key mismatch in traffic.go.

## A) Green-bug traps (5) — all verified clean

### A1 internal/node/traffic.go vs internal/node/traffic_test.go (OCC retry / reseed)
PROD traffic.go:138-147: per-node contrib takes max (`cur > prev`); delta = cur - prev; used += delta; node_usage[key] = cur.
TEST traffic_test.go:167-183: concurrent writer sets `{"1":0,"push_hash":{"1":"x"}}`; asserts BytesBilled=1000, used=1000, push_hash kept.
Verdict: expected used 1000 == delta math (1000-0) under max-scaler (single report); billed-once confirmed by BytesBilled=1000 not 2000. No wrong-semantics assertion.

### A2 internal/telemetry/handler.go vs internal/telemetry/idle_test.go (windows 30/300 + env 45)
PROD handler.go:465 idlePollSeconds = envFloat("OVMANAGER_LIVE_IDLE_POLL_SECONDS", 300); handler.go:472-479 PollSeconds reads os.Getenv EACH call, default 30 (no cache).
TEST idle_test.go:12 idle default 300; idle_test.go:30 PollSeconds default 30; idle_test.go:59-61 env "45" → 45.
Verdict: windows and env override match prod; env re-read each call. Clean.

### A3 internal/billing/ledger.go vs test/billing_tx_test.go (rollback state)
PROD ledger.go:266-282 ApplyUserTraffic writes newUsed/newState only on OCC hit; rollback persists nothing.
TEST billing_tx_test.go:16 seed used=100, node_usage='{}'; billing_tx_test.go:40 asserts used==100, state=="{}" after rollback.
Verdict: "{}" is the seeded fixture restored by rollback, not a ledger write (ledger writes `{"1":150}` on success). Assertion matches rollback-restore semantics. Clean (note: prompt's "used==0" is inaccurate — test asserts used==100).

### A4 internal/users/handler.go live() vs test/users_live_test.go (Connections() keyed by name; double-counting?)
PROD handler.go:118-124 live(): count = telemetry.Connections()[u.name].
PROD telemetry/handler.go:574-589 CollectLiveSnapshot: one ++count per session CN; CN→name via idToName or billing.ExtractUsername; empty skipped.
TEST users_live_test.go:54 one session CN "42"→alice; users_live_test.go:83 asserts alice active_connections=1/online=true; users_live_test.go:91 asserts bob-idle 0/false.
Verdict: single increment per session keyed by name; no double-counting. Clean.

### A5 internal/users/usage_test.go (reserved keys omitted from total_used exactly)
PROD handler.go:646-673 aggregateNodeUsage skips node.IsReservedUsageKey(key) (sync.go:24: push_hash, __reseed); sums remaining `used`.
TEST usage_test.go:28 NodeUsage `{"1":500,"push_hash":{...},"__reseed":true}`; usage_test.go:31 asserts total==500; usage_test.go:34 asserts len(perNode)==1.
Verdict: len(perNode)==1 enforces push_hash/__reseed exclusion; total 500 == key "1" only. Clean.

## B) Panic/hang scan — 1 confirmed finding (resource churn, not panic/hang)

B1 internal/node/client.go:245,253,265,631: requestInner/rawInner build a fresh &http.Client{Transport: &http.Transport{...}} on EVERY call; grep confirms NO CloseIdleConnections anywhere in internal/node. Consequence: per-call Transport alloc, no keep-alive reuse, connection-pool/FD churn. GetUsage/GetSessions/DownloadOVPNClient all route through request/rawInner.
- io.ReadAll half-read + json.Unmarshal-on-nil: NOT confirmed. client.go:382-384 reads the full 409 body then unmarshals (body non-nil); client.go:637 discards ReadAll error but no Unmarshal follows. GetUsage/GetSessions use json.NewDecoder with defer resp.Body.Close(); nil results handled by dataOf. No panic site.
- management.go auth.WriteJSON (writeJSON auth/handler.go:281-285): json.NewEncoder(w).Encode(body), error discarded; no panic (w non-nil). No "leaseWrite" symbol exists.

Overall: A all 5 clean; B has 1 confirmed transport-churn finding, zero panic/hang sites.
