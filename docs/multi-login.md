# Multi-Login (simultaneous connection limit per config)

This feature lets you decide **how many devices can connect with each user's config at
the same time**. It is exposed in the panel as the **Max Logins** field on every user.

- `max_logins = 1` → single login (OpenVPN default behaviour). A second device that
  connects with the same config disconnects/blocks the previous one.
- `max_logins = N` → up to N devices may be connected simultaneously with that config.
- `max_logins = 0` → unlimited (equivalent to OpenVPN `duplicate-cn` with no cap).

The limit counts **simultaneous devices per user** (per config / certificate CN).

---

## Architecture recap

ov-panel is split in two parts:

```
┌────────────┐   HTTP /sync/* (api key)   ┌──────────────────────────┐
│  ov-panel  │ ─────────────────────────► │  node agent (per server) │
│  (this app)│                            │  + OpenVPN server        │
└────────────┘                            └──────────────────────────┘
```

The panel stores users and their settings (now including `max_logins`) and pushes them
to each node over the `/sync/*` HTTP API. The node agent owns the actual OpenVPN server,
so **the limit is enforced on the node** by an OpenVPN `client-connect` script.

Both sides are now implemented:

* **Panel** (this repo): DB column + migration, schemas, CRUD, API endpoints and UI.
* **Node agent** (`ov-node` repo): schema/endpoints to receive the limit, persistence,
  and the OpenVPN `client-connect`/`client-disconnect` enforcement (auto-installed on
  node startup). See `ov-node/docs/multi-login.md`.

The contract between them is described below.

---

## What the panel now sends to nodes

The panel includes `max_logins` in the existing sync calls and adds one dedicated call.

### 1. Create user — `POST /sync/user`
```json
{ "name": "ali-node1", "max_logins": 2 }
```

### 2. Change status — `PUT /sync/user`
```json
{ "name": "ali-node1", "status": "activate", "max_logins": 2 }
```

### 3. Set limit only — `PUT /sync/user/limit`  (implemented in `ov-node`)
```json
{ "name": "ali-node1", "max_logins": 2 }
```
Response (same envelope the node already uses):
```json
{ "success": true, "msg": "User login limit updated successfully" }
```

The `ov-node` agent persists the per-user limit to `/etc/openvpn/limits/<name>` (the
`client-connect` script reads it at connection time). `0` means unlimited. This is
handled automatically by the updated node — no manual work required.

---

## Node side (handled automatically by `ov-node`)

The updated `ov-node` agent sets everything up on startup — no manual server config is
required. For reference, on each node it:

1. Installs `client-connect` / `client-disconnect` scripts to `/etc/openvpn/scripts/`.
2. Ensures `server.conf` contains:
   ```conf
   duplicate-cn
   script-security 2
   client-connect    /etc/openvpn/scripts/ovpanel-client-connect.sh
   client-disconnect /etc/openvpn/scripts/ovpanel-client-disconnect.sh
   ```
3. Stores each client's limit in `/etc/openvpn/limits/<name>` (`0` = unlimited).

On connect, the script reads the limit, counts current sessions for that certificate,
and **rejects the new connection** if the limit is already reached (exit non-zero);
otherwise it accepts and increments the counter, which the disconnect script decrements.

> Why `duplicate-cn`? OpenVPN by default rejects a second simultaneous session that
> presents the same certificate. To allow *N* devices on one config we must enable
> `duplicate-cn` (which by itself means *unlimited*) and then re-impose a counted cap in
> the `client-connect` script. This is the standard way to get an exact N-device limit.

See `ov-node/docs/multi-login.md` for full node-side details.
