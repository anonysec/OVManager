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

## License

Proprietary. See [LICENSE](LICENSE).
