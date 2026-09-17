# Troubleshooting

## I lost my panel URL (the `/random-path/` part)

The panel hides behind a secret path; requests without it get an empty
404 page — that is normal, not a crash. Recover with shell access
(native install):

```bash
cd /opt/ovmanager && sudo uv run main.py --reset-urlpath
```

The panel is served at `/` again. Set a new path in
**Settings → General → Panel URL Path** (tick “I saved the new URL” —
the page redirects you to it). Docker: run the same command inside the
container (`docker exec -it ovmanager …`) or check the installer output /
`install.sh status`. Lost the owner password too? `reset-password` (below)
sets a new one — it does not change or reveal the URL.

## I forgot the owner password

The owner password lives in `/opt/ovmanager/.env` (`ADMIN_PASSWORD=`) and is
read at startup. With shell access, the installer resets it — data is
untouched and every other `.env` line is preserved:

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) reset-password
```

It asks for the new password twice (hidden input, ≥ 12 characters), updates
only that line, keeps the file `0600`, restarts the panel and waits for
`/health`. Scripts and AI skip the prompts:

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh) reset-password --admin-pass 'new-long-password'
# or: OVM_ADMIN_PASS='new-long-password' bash install.sh reset-password
```

Docker installs work the same way — the command finds and restarts the
container. Placeholder-looking passwords (`change-me`, `changeme`, …) are
refused, exactly like the panel.

## The panel is down / I need server-side actions

Run `ovmanager` (alias `ovm`) on the server. The menu covers status, start /
stop / restart, logs, backup, update, TLS and recovery — all without the
web UI. For scripts: `ovmanager status`, `ovmanager logs 200`,
`ovmanager restart`, `ovmanager backup`.

## Login fails with “username or password is incorrect”

* Caps lock / trailing space in the password. Passwords are case-sensitive.
* 5 wrong tries in 5 minutes locks that username for 5 minutes (per-IP and
  per-user limits). Wait and retry — a restart does **not** clear it.
* Still stuck and you have shell access? Use the `reset-password` command —
  see [I forgot the owner password](#i-forgot-the-owner-password) above.

## Browser warns about the certificate

Expected with **self-signed** TLS: the connection *is* encrypted, the
browser just doesn't know who issued the cert. Click Advanced → Proceed.
The warning disappears if you switch to Let's Encrypt with a real domain
and re-run the installer.

## Node stays red

Check in order:

1. **Address**: public IP/hostname of the node server, not `10.x`/`192.168.x`
   unless panel and node share a private network.
2. **Port**: service port (`2083` default) — not the VPN port (`1194`).
3. **API key**: exact copy, no extra spaces. Regenerate only via node
   reinstall with the same `--name` (then update the panel entry too).
4. **TLS switch**: must match the node (`selfsigned`/`le` → on,
   `none` → off). Mismatch = silent connection failure.
5. **Name**: panel node name must equal the node's `--name` exactly.
6. **Firewall**: `2083`/tcp reachable from the panel; on the node,
   `curl -sk https://127.0.0.1:2083/sync/health` should print `{"status":"ok"}`.
   Cloud security groups are the usual culprit.

## Subscription link shows localhost / doesn't download

Subscription and download links are built from the address **you** open the
panel with — so always log in via the public URL
(`https://panel.example.com/...`, not `http://localhost:2095/...` through
an SSH tunnel), and the links you copy will carry that host. Only if you
serve the panel behind a proxy where the request host is wrong, pin it
explicitly: `.env` → `PUBLIC_URL=https://panel.example.com` (or
`--public-url` at install time, or Settings → subscription prefix),
then restart.

## VPN connects but no internet

On the node: IP forwarding + NAT. Native installs handle this via the
`ovnode-nat` service (`systemctl status ovnode-nat`); Docker via the
entrypoint (`CAP_NET_ADMIN` + `/dev/net/tun` mounted). Check
`sysctl net.ipv4.ip_forward` (= 1) and that no other firewall (nftables,
cloud SG) blocks forwarding.

## Installer errors

| Message | Fix |
|---|---|
| `Must run as root (sudo)` | Re-run with `sudo`. |
| `systemd not found — native install needs it` | Use `--mode docker` (WSL, containers) or a full VM. |
| `Port 80 is busy — Let's Encrypt standalone needs it` | Stop whatever listens on 80, or use `--tls-self` for now. |
| `docker compose up failed` | `docker logs ovmanager` — usually a busy port or no disk space. |
| `No answer on /health` | `journalctl -u ovmanager -f` (native) or `docker logs -f ovmanager`; then `install.sh status`. |

## Starting over

Panel keeps data on uninstall unless `--purge` (a backup is made first).
Node data (`/var/lib/ovnode`, `/etc/openvpn`) likewise survives reinstall —
rename-safe only if you keep the same `--name`.
