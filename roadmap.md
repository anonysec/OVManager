# OVManager + OVNode — Consolidated Plan

Lightweight + better UX. Derived from a 10-item UX audit + TLS brainstorm.

---

## Part A — Panel structural (OVManager, items 1–10)

### A1. Install path flattened — **shipped v1.1.2**
`/opt/ovmanager/ovmanager-$VERSION/` → `/opt/ovmanager/`. `release.yml` adds `--prefix=ovmanager-${VER}/` so CI artifacts match `fetch_release --strip-components=1`. UPDATE_STAGE / UPDATE_PREVIOUS rollback mechanic unchanged.

### A2. HTTPS-only, drop `use_tls` — **shipped v1.1.3**
- ✅ NodeCreate `use_tls` field removed. HTTPS mandatory. Cert pin TOFU stored on node.
- Node: refuse to start without TLS cert when `tls_method != "none"`. Installer writes certs at first run.
- Cert pin TOFU on first `/sync/*` call: store `.panel_ca` (PEM) + fingerprint in node.
- Migration between panels with the same key + cert: no ceremony on node.
- New panel with new cert: requires `ovn auth reset` on node (only "exposure" path).

### A3. Node address = host only — **shipped v1.1.3**
Schema: `address: str` (host/IP), `port: int`. URL always `https://{address}:{port}`. Strict normalizer rejects full URLs. ~10 lines in `NodeCreate` schema + form.

### A4. Drop "Apply new VPN settings" checkbox — **shipped v1.1.3**
Save = test + save + apply. Failed connectivity → explicit "node unreachable — configure later" error. New separate button "Save and configure later" for offline adds. ~10 lines.

### A5. Scheduled stale cleanup — **shipped v1.1.5**
`backend/scripts/cleanup_stale_users.py` runs daily via systemd timer. Targets: expired users (`expiry_date < today` AND `is_active=False`). Old audit rows handled in A9. UI button removed.

### A6. TLS settings overhaul — **shipped v1.1.5**

**Storage model (locked):**
- DB is canonical. Settings table carries `ssl_cert_file`, `ssl_key_file`, `acme_domain`, `acme_email`, `cert_method`, etc.
- `.env` carries the same fields, **commented by default**. Operator uncomments a line to force that field's value (read at startup, overrides DB).

**Apply model:**
- Save button writes to DB + writes cert files to disk. Restart required (`ovm restart`) to apply — mirrors x-ui's behavior.

**x-ui-pattern features adopted:** oclc, oclc CLI menu (`ovm tls` extended with `get / renew / replace`), DB-stored settings, `.env` override, restart to apply, ACME integration.

**Auto-renewal:** when ACME is configured, systemd task runs daily at 30 days lead time. Cert renew must complete before expiry. Backend logs warn at 30 / 14 / 7 days.

**UI semantics:** shows effective value per field + "Override via .env" badge when `.env` line is uncommented. Field greyed-out when overridden. Per-field, not whole-section. ~15 lines + small component.

**Cert pin visibility (per node):**
- Both overview (column in Nodes list) and detail (Node edit page).
- Display: fingerprint, expiry, issuer, "Re-pin from current cert" button.

**Display-only fingerprint badge:** green=match, red=mismatch, grey=no-pin. Operator sees MITM at a glance.

**`ovn auth reset`** — credential rotation tool only (panel cert mismatch on rotation, never used for normal panel swap).

**Removed:** "Temporary Certificate" UI block in Settings (operator move). All cert ops via `ovm tls`.

### A7. Alerts restructure
Three rows: errors (red), warnings (yellow), info (blue). Each row: count + first message. Click to expand full list with timestamp + dismiss + snooze. ~30 lines + 1 component.

### A8. Drop "New User Defaults" form fields — **shipped v1.1.4**
Hardcoded: unlimited traffic, 30 days expiry, 1 max_logins. Override via Telegram bot. **Added — shipped v1.1.5:** owner welcome/setup wizard in Telegram bot on first `/start`. 4-step flow (panel URL → ACME yes/no → domain → email). Persisted via migration v17.

### A9. No CSV anywhere
Confirmed: no CSV endpoints, no buttons, no data shape with CSV in mind. Project stays CSV-free.

### A10. Dashboard traffic section fix — **shipped v1.1.4**
Restructure `StreamChart.tsx` + `Dashboard.css`:
- One chart header row, not two segmented rows
- Y-axis labels with units (`GB` / `sessions`)
- Status indicator as visible badge, not dim dot
- Mobile: hide Sessions toggle + 7d period (simplified view)
- Add period comparison ("+24% vs yesterday") next to "Now"
- Fix `preserveAspectRatio="none"` distortion

---

## Part B — PKI + multi-node (Node static, Panel canonical)

#### B1. Panel owns PKI
- Panel generates CA + user certs. Stores in panel DB.
- Panel pushes shared CA + per-user cert/key via `PUT /sync/users/{cn}` (new endpoint, node accepts pushed certs passively).
- Node caches certs in `/etc/openvpn/ovnode/users/<cn>/`, no generation on its own.

#### B2. `.ovpn` generated on panel, uses domain
- `remote <domain>` in `.ovpn` when domain configured. Falls back to IP otherwise with a warning.
- Switch DNS A/AAAA from node A → node B → customers reconnect, same `.ovpn` (no reissue).
- Wiped node → fresh install → re-register → panel re-pushes user certs → customers reconnect, same `.ovpn`.

#### B3. Node = stateless executor
- Node holds transient state per active connection, plus a panel-published user cert cache.
- Node doesn't store admin/user metadata.
- `core/openvpn/users.py:create_user_on_server` rewritten to accept pushed credentials.

#### B4. Per-node fallback IPs in `.ovpn` (cheap)
- Panel lists all registered node IPs as `remote <ip> <port>` lines in `.ovpn` (one per node).
- OpenVPN client tries each in order.

#### B5. Bandwidth aggregation (cheap)
- Each node reports per-user bytes via existing `/sync/usage`.
- Panel sums across nodes → single per-user total.

---

## Part C — OVNode lightweight (shipped v1.0.48)

Already shipped: hot path forks removed (`sanitize` bash builtin, `logger -t` → file append), dedicated `ovnode-openvpn.service`, daily session marker purge, fail-closed CN sanity check. All tests green.

---

## Ship order (suggested)

| Version | Items | Est. lines |
|---|---|---|
| ~~v1.1.5~~ | ~~A5 script+timer, A6 DB+UI+override+ACME, A8 Telegram wizard~~ → shipped | done |
| **OVNode v1.2.0** | B1 PUT /sync/users, B2 .ovpn domain, B3 node stateless, B4 fallback IPs, B5 bandwidth agg | ~300 |
| **v1.1.4** | A7, A10, A8 form fields, B1 (`PUT /sync/users` endpoint) | ~120 |
| **v1.1.5** | A6 UI (override badge, ACME timer), A5 timer, A8 Telegram wizard | ~200 |
| **v1.2.0** | B2, B3, B4, B5 (PKI refactor — breaking; deserves major bump) | ~300 |

Each version = one PR, one CDN release, one smoke test. No bulk reformat, no v2.