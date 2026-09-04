# OVManager quickstart (5 minutes)

You need: a Linux VPS (Debian/Ubuntu recommended), `sudo` access, and about
5 minutes. No Docker knowledge required — the installer asks you questions.

## 1. Install the panel

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)
```

The wizard asks, in order:

| Question | What to answer as a beginner |
|---|---|
| Install mode | `1` Native (simplest on a normal VPS). Pick `2` Docker only if you already use Docker, or you are on WSL/a container without systemd. |
| Port | Press Enter (`2095`). |
| URL path | Press Enter (`random`). This hides your panel from scanners at an address like `/a1b2c3d4/`. **Save the full URL shown at the end.** |
| Admin user | Press Enter (`admin`). |
| Admin pass | Type a long password — or leave blank and the installer generates one and shows it at the end. **Save it.** |
| TLS | `3` Self-signed if this is your first time (encrypted; your browser shows a warning you click through once). `1` Let's Encrypt once you have a domain pointed at the server. `5` None only on a private network you trust. |

Type `y` to confirm the plan, wait a few minutes, and you get a green
**Ready** card:

```text
Open      https:// YOUR-SERVER-IP :2095/ a1b2c3d4 /
Login     admin
Password  (the one you set — or the generated one, save it now)
```

Open that URL, log in. Done — the panel is running.

## 2. Add a VPN node

The panel alone does nothing until you connect a node (the machine that
actually runs OpenVPN):

* **Easiest:** same server. The Ready card prints a ready-to-paste OVNode
  command with an API key already filled in — run it on this server and
  skip to step 3.
* **Separate server:** follow [multi-node](multi-node.md) (2 commands,
  one paste into Nodes → Add Node).

## 3. Create a user and connect

1. **Users → Add User** — name, expiry, traffic limit. Leave the rest default.
2. Click the download icon on the user row, pick a node, save the `.ovpn` file.
3. Import it into any OpenVPN client (Windows/macOS: OpenVPN Connect,
   Android/iOS: OpenVPN app, Linux: NetworkManager or `openvpn --config`).

That is the whole flow. Details: [single-vps](single-vps.md),
[multi-node](multi-node.md). Stuck? [troubleshooting](troubleshooting.md).

## Unattended install (scripts / AI)

```bash
curl -sSL https://anonysec.github.io/OVManager/install.sh \
  | sudo bash -s -- -y --mode native --admin-pass 'choose-a-long-password'
```

Useful flags: `--port 2095` `--path root` (serve at `/` instead of a
secret prefix) `--tls-self` `--dry-run` (print plan, change nothing).
`CI=true` implies `-y`. Full list: `bash install.sh --help`.
Omit `--admin-pass` under `-y` and a password is generated and printed.

## Update / uninstall / status

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) update
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) status
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) uninstall
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) uninstall --purge  # also deletes data
```
