# OVManager + OVNode — Consolidated Plan

Lightweight + better UX. From the 10-item audit, TLS brainstorm, and front-end polish round.

---

## Part A — Panel structural (OVManager, items 1–10)

### A1. Install path flattened — **shipped v1.1.2**
`/opt/ice-manager/ovmanager-$VERSION/` → `/opt/ovmanager/`. `release.yml` adds `--prefix=ovmanager-${VER}/` so CI artifacts match `fetch_release --strip-components=1`. UPDATE_STAGE / UPDATE_PREVIOUS rollback mechanic unchanged.

### A2. HTTPS-only, drop `use_tls` — **shipped v1.1.3**
NodeCreate `use_tls` removed. HTTPS mandatory. Cert pin TOFU stored on node. Migration between panels with the same key + cert: no ceremony on node. New panel with new cert: requires `ovn auth reset`.

### A3. Node address = host only — **shipped v1.1.3**
`address: str` (host/IP), `port: int`. URL always `https://{address}:{port}`. Validator rejects `://` / `:` / `/`.

### A4. Drop "Apply new VPN settings" checkbox — **shipped v1.1.3**
Save = test + save + apply. Failed connectivity → explicit error. New "Save and configure later" button for offline adds.

### A5. Scheduled stale cleanup — **shipped v1.1.5**
`backend/scripts/cleanup_stale_users.py` runs daily via systemd timer. UI button removed.

### A6. TLS settings overhaul — **shipped v1.1.5**
DB-canonical settings + `.env` overrides (commented by default). Save + `ovm restart` to apply. ACME weekly timer + logrotate. `ovm tls get/renew/replace`. Cert pin per-node (green/red/grey chip). Telegram owner welcome wizard (4-step). "Temporary Certificate" UI removed.

### A7. Alerts restructure — **shipped v1.1.4**
Three grouped rows (errors / warnings / info). Expand + dismiss + snooze per row.

### A8. Drop "New User Defaults" form fields — **shipped v1.1.4**
Hardcoded defaults: unlimited traffic, 30 days expiry, 1 max_logins. Telegram bot override.

### A9. No CSV anywhere
Project stays CSV-free.

### A10. Dashboard traffic section fix — **shipped v1.1.4**
Header breathing room, axis units, Live/Offline badge, period-delta chip, mobile-hides-secondary, SVG bounded.

### A11. Add Node form cert section — **shipped v1.1.6**
Drop the `ovnode://` bundle URI (single-paste UX was awkward for the ~2.3KB PEM). Keep current Add Node form layout. Drop the "Quick setup" subsection. Add `cert` textarea in Security section under `api_key`. PEM validated (`-----BEGIN…-----`). Stored as panel's TOFU pin in `node.server_ca`. Node installer prints cert PEM + API key + IP/port at end of install (separate lines, no URI bundle).

### A12. UserManagement filter cleanup — **shipped v1.1.8**
4 chips only: `[All] [Active] [Disabled] [Expiring]`. Drop `Online` (per-row indicator), `Near quota` (vague), `Unlimited` (default state). `Expiring` = users with 1–7 days remaining. Expired users surface via per-row badge + sort-by-expiry-ascending. x-ui / 3x-ui convention.

### A13. Add User modal — **shipped v1.1.7**
Drop modal title (page heading already says "Users"). Restructure 3 fieldsets → single 2-col grid (no ALL CAPS legends). Hero the username input + Suggest button. Devices = 3 clickable cards (1/2/∞), not tiny chips. Defaults inline as placeholders. Single primary CTA. Success state = single checkmark + Copy subscription link only (Download moves to row's "⋯" menu).

---

## Part B — PKI + multi-node (Node static, Panel canonical)

### B1. Panel owns PKI — **shipped OVNode v1.2.0**
`PUT /sync/users/{cn}` + `PUT /sync/pki` endpoints on node side. Panel pushes user certs + CA. Node stores passively. `create_user_on_server` writes request PEMs (no easy-rsa fork).

### B2. `.ovpn` generated on panel, uses domain — **shipped OVManager v1.2.0**
`remote <domain>` when panel has a domain configured. Falls back to IP with warning. Domain switch DNS A/AAAA → customers reconnect, same `.ovpn`. Wiped node → re-register → panel re-pushes user certs → customers reconnect.

### B3. Node = stateless executor — **shipped OVNode v1.2.0**
`create_user_on_server` accepts pushed credentials. Legacy local generation kept as documented fallback. OpenVPN reload via management socket.

### B4. Per-node fallback IPs in `.ovpn` — **shipped OVManager v1.2.0**
Panel lists every registered node IP as a `remote <ip> <port>` line in the `.ovpn`. OpenVPN client tries each in order. No DNS dependency.

### B5. Bandwidth aggregation across nodes — **shipped OVManager v1.2.0**
Per-node `/sync/usage` already exists. Panel sums per-user bytes across nodes → single per-user total in UI.

---

## Part C — OVNode lightweight (shipped v1.0.48)

Hot-path forks removed (`sanitize` bash builtin, `logger -t` → file append), dedicated `ovnode-openvpn.service`, daily session marker purge, fail-closed CN sanity check.

## Part D — Operator settings (OpenVPN focus, lightweight, no reseller scope)

Picked from the 3x-ui / PasarGuard audit. Only items 1, 2, 6, 7, 10.
No RBAC, no 2FA, no HWID, no SMTP/Discord — selling lives in another project.

### D1. Subscription surface — profile, not just URL
Sub page gets: profile title, support URL, announce text, update interval.
`.ovpn` keeps working as-is; this is the customer-facing text around it.
Skip: UA→format rules, per-format toggles, app catalog (Xray-world, not ours).

### D2. Threshold alert engine (Telegram only)
Per-event toggles + thresholds, all Telegram, each with test button:
days-left (default 3), usage % (default 80), node down, CPU load.
Today's severity groups stay as the inbox; D2 is the trigger layer above them.

### D6. Cleanup page (maybe)
Bulk delete expired / disabled with date filter + dry-run preview,
reset-all-usage, purge usage tables. Today's daily timer keeps running;
this is the manual lever for incidents. Ship only if timer proves insufficient.

### D7. Backup as a real story
Schedule + retention count + Telegram notify (DB file shipped on cron).
Settings-backed, no new deps (sqlite file copy + existing bot).

### D10. In-panel ops
Restart panel, update check, geo-file refresh from Settings → System.
Kills the last SSH-only routine tasks. No reset-to-default (too destructive
without RBAC to gate it).

---

## Ship order (append)

| Version | Items | Est. lines | Status |
|---|---|---|---|
| v1.1.2 | A1 path flatten | ~30 | ✅ shipped |
| v1.1.3 | A2+A3+A4 form/schema cleanup | ~150 | ✅ shipped |
| v1.1.4 | A7+A10+A8 form drop | ~200 | ✅ shipped |
| v1.1.5 | A5+A6+A8 wizard | ~300 | ✅ shipped |
| OVNode v1.2.0 | B1+B3 panel-owned PKI | ~300 | ✅ shipped |
| ~~v1.1.6~~ | ~~A11 Add Node cert section, drop ovnode:// bundle~~ → shipped | done |

| ~~v1.1.8~~ | ~~A12+A13 polish batch~~ → shipped | done |
| ~~v1.2.0~~ | ~~B2+B4+B5 panel-side PKI~~ → shipped | done |
| **v1.2.1** | **Router dedup fix (route name uniqueness)** | **shipping now** |
| v1.2.7 | D10 in-panel restart button (update check UI exists; geo dropped — no geo files in product) | ~80 | planned |
| v1.2.8 | D7 backup schedule + retention + TG notify wiring gaps | ~150 | planned |
| v1.2.9 | D2 threshold alerts (days-left, usage %, node down, CPU) + test | ~250 | planned |
| v1.3.0 | D1 subscription profile (title, support URL, announce, interval) | ~120 | planned |
| v1.3.1 | D6 cleanup page w/ dry-run (only if timer proves insufficient) | ~200 | maybe |

Each version = one PR, one CDN release, one smoke test. No bulk reformat, no v2.