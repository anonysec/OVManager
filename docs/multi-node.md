# Multi-node: panel on one server, VPN nodes elsewhere

The panel is the control plane; each OVNode is a VPN server. Nodes never
call the panel — the panel connects **out to** each node — so you can move
or replace the panel without touching the nodes.

## 1. Install a node (on the VPN server)

```bash
bash <(curl -sSL https://anonysec.github.io/OVNode/install.sh)
```

Wizard cheat-sheet:

| Question | Answer |
|---|---|
| Node name | A short id like `eu-1`. **Must match the name you type in the panel later — exactly.** Renaming later orphans the old data folder, so pick once. |
| Service port | Enter (`2083`). |
| OpenVPN ports | Enter (`1194`). Add `443,8443` if your users are on networks that block VPN ports — clients fail over automatically. |
| API key | Leave blank (auto-generates a strong one). **Copy it from the summary.** |
| Mode | `1` Native on a normal VPS. `2` Docker if you prefer containers. |
| TLS | `3` Self-signed for the first node (then turn TLS **on** in the panel). `1` Let's Encrypt once you have a domain. Avoid `5` None over the internet — the API key travels in cleartext. |

The green summary shows everything the panel needs:

```text
Node      eu-1
Address   203.0.113.10        <- the server's PUBLIC IP (see note below)
Service   https://203.0.113.10:2083
API key   abc123...           <- copy this
```

> **Private vs public IP:** if the summary shows a `10.x`/`192.168.x` address,
> the server is behind NAT (common on some clouds). Use the server's **public**
> IP as the panel address instead.

Unattended equivalent:

```bash
curl -sSL https://anonysec.github.io/OVNode/install.sh \
  | sudo bash -s -- install -y --name eu-1 --tls selfsigned \
    --vpn-ports 1194,443 --api-key "$(openssl rand -hex 32)"
```

## 2. Register it in the panel

**Nodes → Add Node**, or paste the `ovnode://` bundle if your installer
printed one — it fills every field:

| Field | Value from the node summary |
|---|---|
| Name | `eu-1` (exact match) |
| Address | public IP / hostname |
| Port | `2083` |
| API key | the generated key |
| TLS | on if the node used selfsigned/LE, off only if the node used None |
| OVPN port / protocol | `1194` / whatever the node summary says |

Save — the row turns green within seconds. If it stays red, see
[troubleshooting](troubleshooting.md#node-stays-red).

## 3. Firewall

The node installer opens `ufw`/`firewalld` automatically. If your provider
has its **own firewall** (AWS security groups, Hetzner Cloud firewall,
etc.), open these yourself:

* `1194` UDP **and** TCP (plus any extra VPN ports) — from everywhere
* `2083` TCP — only from the panel's IP
* Panel port (`2095`) — only from your IP

## 4. Later: update / check / remove

```bash
bash <(curl -sSL https://anonysec.github.io/OVNode/install.sh) status    # health + cert expiry
bash <(curl -sSL https://anonysec.github.io/OVNode/install.sh) update    # backs up data first
```
