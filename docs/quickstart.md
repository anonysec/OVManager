# OVManager quickstart (5 minutes)

You need: a Linux VPS (Debian/Ubuntu recommended), `sudo` access, and about
5 minutes. No Docker knowledge required — the default install asks nothing.

## 1. Install the panel

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

The menu offers **Install** (recommended) or **Install with Docker**. Both
install with safe defaults and no answers: native mode, port `2095`, a random
secret URL path, admin user `admin`, self-signed TLS — and a one-time **claim
key** instead of a password (you choose the password in the browser). Answer
`1` at the start menu, or re-run with `interactive`, for the Custom path that
asks everything:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
```

| Question | What to answer as a beginner |
|---|---|
| Install mode | `1` Native (simplest on a normal VPS). Pick `2` Docker only if you already use Docker, or you are on WSL/a container without systemd. |
| Port | Press Enter (`2095`). |
| URL path | Press Enter (`random`). This hides your panel from scanners at an address like `/a1b2c3d4/`. **Save the full URL shown at the end.** |
| Admin user | Press Enter (`admin`). |
| Owner password | Not asked here. The installer prints a claim key; you choose the password in the browser after pasting that key. **Save the key.** |
| TLS | `1` Self-signed (default) if this is your first time (encrypted; your browser shows a warning you click through once). `2` Let's Encrypt once you have a domain pointed at the server. Plain HTTP is not offered. |

Type `y` to confirm the plan, wait a few minutes, and you get a green
**Ready** card:

```text
Open      https:// YOUR-SERVER-IP :2095/ a1b2c3d4 /claim
Claim key (one-time, spent when you claim)
Login     admin
```

Open that URL, paste the key, choose the owner password. Done — the panel is
running, and that password is the one you log in with from then on.

## 2. Add a VPN node

The panel alone does nothing until you connect a node (the machine that
actually runs OpenVPN):

* **Easiest:** same server. The Ready card prints a ready-to-paste OVNode
  command with an API key already filled in — run it on this server and
  skip to step 3.
* **Separate server:** follow [multi-node](multi-node.md) (2 commands,
  one paste into Nodes → Add Node).

## 3. Create a user and connect

1. **Users → Add User** — name, expiry, traffic limit. Leave the rest default
   (defaults come from Settings → Defaults: 30 days, 1 device).
2. The panel immediately offers the handoff: **Get Config** (pick a node,
   save the `.ovpn` file) or **Copy subscription link**. You can do both
   later from the user row's download icon.
3. Import the config into any OpenVPN client (Windows/macOS: OpenVPN Connect,
   Android/iOS: OpenVPN app, Linux: NetworkManager or `openvpn --config`).

That is the whole flow. Details: [single-vps](single-vps.md),
[multi-node](multi-node.md). Stuck? [troubleshooting](troubleshooting.md).

## Unattended install (scripts / AI)

```bash
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- -y --docker
```

Three flags: `--docker`, `-y/--yes` and `-h/--help`; everything else is an
`OVM_*` variable that is also the wizard's default — `OVM_PORT`,
`OVM_PATH=root`, `OVM_TLS=le` with `OVM_TLS_DOMAIN=panel.example.com`, or
`OVM_VERSION=v1.2.3` to pin a release. `CI=true` implies `-y`. `-p/--pass`,
`--mode` and `--tls*` still work but are deprecated and print their
replacement. Full list: `bash install.sh --help`. The port and the secret URL
path are generated for you.

## Update / uninstall / status

These live in `ovm` (alias `ovmanager`), installed by the installer and
refreshed on every update — no need to re-download `install.sh`:

```bash
sudo ovm update         # staged update with automatic failover
ovm status              # service, health, version, panel URL
sudo ovm uninstall      # remove the app, keep data
sudo ovm uninstall --purge  # also deletes data
```
