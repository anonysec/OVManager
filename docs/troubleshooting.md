# Troubleshooting

## I lost my panel URL (the `/random-path/` part)

The panel hides behind a secret path. Requests without it get an empty 404 page.
That is normal, not a crash. With shell access, clear the prefix:

```bash
sudo ovm reset-urlpath
```

The panel is served at `/` again — log in as usual and set a new path in
**Settings → General → Panel URL Path**. Tick “I saved the new URL” when you do
(the old address stops working immediately). `ovm status` prints the current
panel URL at any time.

Without the `ovm` command, the same reset runs from the install tree:

```bash
cd /opt/ovmanager && sudo .venv/bin/python main.py --reset-urlpath
```

Docker: `docker exec ovmanager /app/.venv/bin/python main.py --reset-urlpath`.

Lost the owner password too? See the next section. The password reset does not
change or reveal the URL path.

## I forgot the owner password

The owner credential is a row in the panel database: a bcrypt hash in the
`admins` table, keyed by the `ADMIN_USERNAME` in `.env`. `.env` holds no
password, and the `ADMIN_PASSWORD` / `ADMIN_PASSWORD_HASH` lines from older
installs are ignored at boot (the panel logs a warning about them, and they can
be deleted).

With shell access:

```bash
sudo ovm reset-password -p 'new-long-password'
# or, to keep the secret out of the process list:
OVM_PASS='new-long-password' sudo ovm reset-password
```

The password must be at least 8 characters, and placeholder values
(`change-me`, `changeme`, `change_me`, `password123`, `admin123`) are refused,
exactly as in the panel. The command rewrites the owner row, restarts the panel
and waits for `/health`. It never echoes or logs the value.

On a Docker install this command rewrites `.env` instead of the database row,
and the panel does not read it, so the password is left unchanged. That is a
known defect; until it is fixed, treat the native install as the supported path
for this recovery.

## The panel is down, or I need server-side actions

Run `ovm` on the server. It needs no browser:

```bash
sudo ovmanager status      # or ovm status
sudo ovmanager logs 200    # 200 lines; logs -f follows
sudo ovmanager restart
sudo ovmanager backup
sudo ovmanager recovery    # reprints the panel URL and login name
```

## Login fails with "username or password is incorrect"

* Check for caps lock or a trailing space. Passwords are case-sensitive.
* Five failed attempts for the same username and IP lock that login for five
  minutes. A restart does not clear it. Twenty failures from one IP, across any
  usernames, trip the same lock.
* Still locked out? Set a new password with `sudo ovm reset-password` (above).

## The browser warns about the certificate

Expected with self-signed TLS. The connection is encrypted; the browser just does
not recognise the issuer. Click Advanced, then Proceed. The warning disappears
once a real certificate is in place:

```bash
sudo ovm https --domain panel.example.com   # Let's Encrypt, needs port 80 free
sudo ovm https --self                       # a fresh self-signed pair
sudo ovm tls-status                         # what is installed, and until when
```

## `ovm status` or `ovm doctor` says the panel is unreachable

The health probe pins the certificate recorded in `.env` (`SSL_CERTFILE`) and
falls back to an unverified request only when it cannot read that file, so a
healthy self-signed panel reads as healthy. The hostname is deliberately not
checked: the installer's certificate carries the public IP as its common name
and has no subject alternative names, while the probe dials `127.0.0.1`.

What does fail the probe is the panel serving a different certificate from the
one in `.env`, which usually means the pair was replaced after the last install.
Compare `ovm tls-status` (what is on disk) with `ovm logs` (what is served).

## Node stays red

Check in order:

1. **Address**: the node's public IP or hostname. A `10.x` or `192.168.x`
   address only works when the panel and the node share a private network.
2. **Port**: the node's service port (`2083` by default), not the VPN port
   (`1194`).
3. **API key**: an exact copy, with no leading or trailing space.
   `sudo ovn credentials` reprints the node's key and bundle.
4. **TLS switch**: must match the node. `selfsigned` or `letsencrypt` on the
   node means the panel's TLS toggle is on; `none` means off. A mismatch is a
   silent connection failure.
5. **Name**: the panel entry must match the node's own name exactly.
   `sudo ovn credentials` prints it.
6. **Firewall**: `2083/tcp` reached from the panel. On the node,
   `curl -sk https://127.0.0.1:2083/sync/health` should print
   `{"status":"ok"}`. Cloud security groups are the usual culprit.

## No node-down Telegram alert

The panel probes every node about every five minutes and messages the owner once
per outage. Nothing arrives? Check in order:

1. **Bot configured**: token and owner ID saved in **Settings → Bot**, and
   *Start* tapped in the bot once (Telegram refuses to message a user who never
   started the chat).
2. **Alert enabled**: **Settings → Alerts → "Node goes down or comes back"**.
3. **Give it a probe**: detection happens on the five-minute collector, so allow
   about five minutes after the node went down.
4. **One message per outage**: a node that stays down is not re-alerted every
   five minutes. You get one message when it goes down and one when it answers
   again. If the bot was broken during the outage, the panel keeps retrying, so
   the alert arrives late rather than never.
5. **You deleted and re-added the node**: alerts key off the panel's node entry,
   and re-adding it resets the already-alerted state.

## Subscription link says localhost, or the download fails

Subscription and download links are built from the address you opened the panel
with. Log in via the public URL (`https://panel.example.com/...`) rather than
through an SSH tunnel to `localhost`, and the links you copy carry that host.

Behind a proxy that reports the wrong host, pin the address instead: set
`PUBLIC_URL=https://panel.example.com` in `.env` (or pass
`OVM_PUBLIC_URL=https://panel.example.com` at install time, or set the
subscription prefix in Settings), then restart the panel.

## VPN connects but there is no internet

That is NAT on the node. The node installer handles it: native installs add an
`ovnode-nat` service (`systemctl status ovnode-nat`), Docker installs do it in
the entrypoint. If traffic still does not flow, check `sysctl net.ipv4.ip_forward`
(needs to be `1`) and that no other firewall (nftables, a cloud security group)
blocks forwarding.

## Installer errors

| Message | What to do |
|---|---|
| `Must run as root (sudo)` | Re-run the command with `sudo`. |
| `systemd not found — native install needs it` | Install with `--docker` (or `OVM_MODE=docker`), or use a full VM. |
| `Port 80 is busy — Let's Encrypt standalone needs it` | Free port 80, or install with `OVM_TLS=self` and switch later with `ovm https`. |
| `docker compose startup failed` | `docker logs ovmanager`. Usually a busy port or a full disk. |
| `No answer on /health` | `journalctl -u ovmanager -f` for a native install, `docker logs -f ovmanager` for Docker, then `sudo ovm doctor`. |
| `Download … is not a release archive` or `Release checksum mismatch` | The installer predates the release it is trying to fetch. Re-bootstrap with the current one-liner: `bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)`, then run the update again. |
| `Could not fetch …/scripts/lib/…` | The installer could not reach its own helper library, which it needs before it can do anything. Check outbound HTTPS, then retry. |

## Starting over

Uninstalling the panel keeps its data unless `--purge` is passed, and purging
first writes a snapshot to `/var/backups/panel-pre-purge-ovmanager-*.tar.gz`.

```bash
sudo ovm uninstall          # app removed, data kept at /var/lib/ovmanager
sudo ovm uninstall --purge  # also removes the data directory and its backups
```

Certificates issued inside the panel live under `DATA_DIR/tls` and go with
`--purge`. A pair created at install time stays: the self-signed one lives in
`/etc/ssl/self-signed`, which OVNode shares, and a Let's Encrypt pair lives in
`/etc/letsencrypt`.

Node data (`/var/lib/ovnode`, `/etc/openvpn`) survives a node reinstall. Reusing
it is only safe with the same node name: a different name reads a different data
folder.
