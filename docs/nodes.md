# Nodes: panel on one server, VPN on the same or another

The panel is the control plane: it holds users, quotas and settings. Each OVNode
is a VPN server: it owns OpenVPN, the certificates and the per-user configs.

The panel connects **out to** each node, and nodes never call the panel, so you
can move or replace the panel without touching the VPN servers. One panel drives
as many nodes as you like, and each node is reached only by the panel.

## 1. Install OVNode

On every machine that should carry the VPN:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVNode/main/install.sh)
```

Answer `1` to install natively or `2` for Docker. The recommended install asks
nothing: node name `ovnode`, service port `2083`, UDP, VPN port `1194`,
self-signed TLS, and a generated API key. Run the installer with `interactive`
to answer the questions instead:

| Question | What to answer |
|---|---|
| Node name | A short id like `eu-1`. **It must match the name you type in the panel later, exactly.** Renaming it later orphans the old data folder. |
| Service port | Enter (`2083`). |
| OpenVPN port(s) | Enter (`1194`). Add `443,8443` if your users are on networks that block VPN ports; clients fail over automatically. |
| API key | Leave blank and a strong one is generated. **Copy it from the summary.** |
| Transport | `udp` unless UDP is blocked where your users are, then `tcp`. |
| Mode | `1` Native on a normal VPS. `2` Docker if you prefer containers. |
| TLS | `1` Self-signed, then switch TLS **on** in the panel. `2` Let's Encrypt once a domain points here. Plain HTTP is not offered: the API key would travel in clear text. |

Unattended, for scripts:

```bash
curl -sSL https://raw.githubusercontent.com/anonysec/OVNode/main/install.sh \
  | OVN_NAME=eu-1 OVN_KEY="$(openssl rand -hex 32)" OVN_VPN_PORTS=1194,443 \
    sudo -E bash -s -- --yes
```

Node settings follow the same rule as the panel installer: the same three flags,
`-y/--yes`, `--docker` and `-h/--help`, and everything else is an `OVN_*`
variable (`OVN_NAME`, `OVN_KEY`, `OVN_PORT`, `OVN_VPN_PORTS`, `OVN_PROTO`,
`OVN_TLS`, `OVN_TLS_DOMAIN`). `bash install.sh --help` lists them.

The install ends with a summary card:

```text
Node      eu-1
Service   https://203.0.113.10:2083
OpenVPN   1194
API key   abc123…            (generated — save this)
Bundle    ovnode://eu-1@203.0.113.10:2083?key=abc123…&tls=1
```

Copy the **Bundle** line. Pasting it into the panel's Add Node form fills in the
name, address, port, API key and TLS setting at once.

> **Private or public address:** if the card shows a `10.x` or `192.168.x`
> address, the server is behind NAT (common on some clouds). Use its **public**
> address in the panel instead.

## 2. Same server as the panel

The easiest topology, and enough for personal use and small teams.

1. Install the panel ([quickstart](quickstart.md)), claim it, and log in.
2. Install OVNode on the same machine with the command above. The recommended
   install names it `ovnode`.
3. In the panel, **Nodes → Add Node**: paste the node's `Bundle` line, or fill in
   name `ovnode`, address `127.0.0.1`, port `2083`, the API key, TLS on.
4. The node row turns green. Create a user, download the `.ovpn`, connect.

No firewall work is needed: the node API is only reachable on the loopback
address.

Outgrowing one box? Add remote nodes at any time. Nothing about the panel
install changes.

## 3. Separate servers

Panel on one machine, VPN on one or more others.

1. Install OVNode on the VPN server (above) and note its name, public address,
   port and API key. `sudo ovn credentials` reprints all of them.
2. In the panel, **Nodes → Add Node**:

   | Field | Value |
   |---|---|
   | Name | The node's own name: `ovnode` unless you set `OVN_NAME` (or answered the wizard). It must match exactly. |
   | Address | Public IP or hostname |
   | Port | `2083` |
   | API key | The node's key |
   | TLS | On. The node installer always encrypts. |
   | OVPN port / protocol | From the node summary (`1194` / `udp`) |

   Pasting the `Bundle` line does all of this in one step.
3. Save. The row turns green within seconds. If it stays red, see
   [troubleshooting](troubleshooting.md#node-stays-red).

## Ports and firewall

The node installer opens `ufw` or `firewalld` automatically. If your provider
runs its own firewall (AWS security groups, Hetzner Cloud firewall, and so on),
open these by hand:

| Port | What | Reachable from |
|---|---|---|
| `1194` UDP **and** TCP | OpenVPN clients (plus any extra VPN ports) | Everywhere |
| `2083` TCP | Node API | Only the panel's address |
| `2095` TCP | Panel web UI | Only you |

The same table for a single-server install: `2095` from your browser, `2083` on
`127.0.0.1` only, `1194` from your users.

## Later: update, check, remove

```bash
sudo ovn status     # agent health, OpenVPN state, certificate expiry
sudo ovn update     # staged update, backs up data first
sudo ovn logs       # recent agent logs
```

Node data lives in `/var/lib/ovnode` plus `/etc/openvpn`; panel data lives in
`/var/lib/ovmanager`. Back up those paths and you can rebuild on another machine.

`ovn uninstall` removes the agent and keeps the data, unless `OVN_PURGE=1`.
Uninstalling the panel keeps its data unless you pass `--purge`.
