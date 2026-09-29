# OVManager quickstart

You need a Linux VPS (Debian or Ubuntu recommended), `sudo`, and about five
minutes. No Docker knowledge is required: the default install asks nothing.

## 1. Install the panel

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
```

The menu offers two installs:

| Choice | What happens |
|---|---|
| `1` Install (recommended) | Native install as a systemd service. No questions at all: port `2095`, a random secret URL path, admin user `admin`, self-signed TLS. |
| `2` Install with Docker | The same, as a container. Pick this only if you already use Docker, or if the host has no systemd (WSL, a container). |

To answer the settings yourself, run the wizard instead:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
```

It walks five steps. Press Enter to accept every default:

| Step | Default | Notes |
|---|---|---|
| Install mode | `1` Native | `2` Docker for a host without systemd. |
| Panel port | `1` `2095` | `2` Custom, `3` random. |
| Panel URL path | `random` | A prefix like `/a1b2c3d4/` hides the panel from scanners. `root` serves it at `/`. |
| Admin user | `admin` | The owner login name. |
| Certificate | `1` Self-signed | Encrypted, with one browser warning to click through. `2` Let's Encrypt needs a domain pointed here and a free port 80. `3` Let's Encrypt for this IP. `4` Your own key and certificate. Plain HTTP is not offered. |

There is no password question. The install finishes with a **Ready** card:

```text
Ready — claim your panel
────────────────────────────────────────
Open      https://203.0.113.10:2095/a1b2c3d4/claim
Claim key 9f1c8b2e…  (one-time)
Login     admin
Manage    ovm  (status, logs, backup, restore, TLS, recovery)
Logs      journalctl -u ovmanager.service -f
Data      /var/lib/ovmanager
────────────────────────────────────────
```

**Save the whole URL and the claim key.** Then:

1. Open that URL in a browser. The certificate warning is expected for a
   self-signed certificate.
2. Paste the claim key and choose the owner password (at least 8 characters, no
   placeholder like `change-me`).
3. You are logged in as the owner. That password is the one you use from now on,
   and it lives as a hash in the panel database, never in `.env`.

The key is spent by the claim. If you lose it before claiming,
`sudo ovm owner-claim` prints a new one. If the panel is already claimed and you
lose the password, `sudo ovm reset-password`.

## 2. Add a VPN node

The panel manages users; it does not carry a VPN by itself. Each VPN server runs
OVNode.

* **Same server:** install OVNode here. It takes a couple of minutes and needs
  no panel address.
* **Separate server:** install OVNode there, and register it in the panel.

Both routes, with the exact commands and the firewall list, are in
[nodes](nodes.md). The panel also keeps a three-step checklist at `/setup`, with
the node installer command in it. Until it is finished, the Home page carries a
banner linking there.

Whichever you pick, the node installer ends with a summary:

```text
Node      ovnode
Service   https://203.0.113.10:2083
OpenVPN   1194
API key   abc123…            (generated — save this)
Bundle    ovnode://ovnode@203.0.113.10:2083?key=abc123…&tls=1
```

In the panel, **Nodes → Add Node** either takes those fields one by one, or you
paste the `Bundle` line and it fills them all in. The row turns green within
seconds.

## 3. Create a user and connect

1. **Users → Add User**: name, expiry date, traffic limit. The rest can stay at
   the defaults (Settings → Defaults sets them).
2. The panel offers the handoff straight away: **Get Config** (choose a node and
   save the `.ovpn` file) or **Copy subscription link**. Both stay available
   from the user's row afterwards.
3. Import the `.ovpn` into any OpenVPN client: OpenVPN Connect on Windows and
   macOS, the OpenVPN app on Android and iOS, NetworkManager or
   `openvpn --config` on Linux.

That is the whole flow. To take a second look at the layout, see
[how it works](how-it-works.md). Stuck? [Troubleshooting](troubleshooting.md).

## Unattended install

For scripts and CI:

```bash
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --yes

# with Docker
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | sudo bash -s -- --docker --yes
```

Three flags: `-y/--yes`, `--docker`, `-h/--help`. Every other setting is an
`OVM_*` variable, and each one is also the wizard's default, so an unattended run
and an interactive run cannot disagree:

```bash
# every OVM_* variable is passed to sudo's environment after the pipe
curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh \
  | OVM_PORT=8443 OVM_PATH=root OVM_TLS=le OVM_TLS_DOMAIN=panel.example.com \
    sudo -E bash -s -- --yes
```

`OVM_PATH` takes `random`, `root` or a name; `OVM_TLS` takes `self`, `le`,
`le-ip` or `custom` (with `OVM_TLS_KEY` and `OVM_TLS_CERT`); `OVM_VERSION` pins
an update to one release; `OVM_REPO` points everything at a fork. `CI=true`
implies `--yes`. The older flag spellings (`-p/--pass`, `--mode`, `--tls*`, `-i`)
still work and each prints what replaces it. The full list is
`bash install.sh --help`.

The claim key is printed either way, and the panel still needs the browser step
to set the owner password.

## Update, status, uninstall

These live in `ovm` (alias `ovmanager`), installed by the installer and refreshed
by every update, so there is no need to download `install.sh` again:

```bash
sudo ovm status             # service, health, version, panel URL
sudo ovm update             # staged update, rolls back if the panel does not come up
sudo ovm uninstall          # remove the app, keep data
sudo ovm uninstall --purge  # also delete the data directory
```
