# OVManager

OpenVPN management panel. Works with [OVNode](https://github.com/anonysec/OVNode) for node-side VPN management.

## Install

```bash
bash <(curl -sSL https://anonysec.github.io/OVManager/install.sh)
```

With options:

```bash
bash <(curl -sSL URL) -- --port 2095 --path dash --admin-user admin --admin-pass mypassword
```

## Update / Uninstall

```bash
# Update
bash <(curl -sSL URL) update

# Uninstall
bash <(curl -sSL URL) uninstall
```

## Docker

```bash
bash <(curl -sSL URL) --docker
```

## Manual Install

```bash
git clone https://github.com/anonysec/OVManager.git /opt/ovmanager
cd /opt/ovmanager
cp .env.example .env  # edit with your settings
pip install uv && uv sync
cd frontend && npm ci && npm run build
uv run main.py
```

## Panel path (URLPATH)

The panel can be served under a secret URL prefix (e.g. `/k3f9xq2m/`) which
hides it from internet scanners: requests outside the prefix get an empty
response, not even a 404.

- The installer generates a **random path by default** (override with
  `--path mypath`, or `--path root` to serve at `/`).
- Change it anytime in **Settings → General → Panel URL Path** — takes
  effect immediately, no restart. Prefixes of real routes (`api`, `assets`,
  `health`, subscription path, …) are rejected automatically.
- The prefix is scanner-hiding, **not authentication** — admin login + rate
  limiting protect the panel either way. Subscription links (`/sub/...`)
  and `/health` are intentionally served without the prefix: links must be
  shareable with users and healthchecks must keep working.

Forgot the path? Recover with shell access:

```bash
cd /opt/ovmanager && uv run main.py --reset-urlpath   # panel goes back to /
```

## License

Proprietary. See [LICENSE](LICENSE).
