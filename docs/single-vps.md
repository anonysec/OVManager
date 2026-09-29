# All-in-one: panel + node on one VPS

This is the easiest topology: one server runs everything. Good for personal
use and small teams.

## Steps

1. Install the panel ([quickstart](quickstart.md)). At the end, the green
   **Ready** card prints the panel **URL**, the **login name** and the
   **generated password** — save all three.
2. Install OVNode on the **same server** (it installs the agent +
   OpenVPN, about 2–3 minutes):

   ```bash
   curl -sSL https://raw.githubusercontent.com/anonysec/OVNode/main/install.sh \
     | sudo bash -s -- -y --name node-1 --tls selfsigned \
       -p "$(openssl rand -hex 32)"
   ```

   Keep the key it prints in the summary (or the one you passed) — the
   panel needs it next.
3. Back in the panel: **Nodes → Add Node** and fill in:
   * Name: `node-1` (must match exactly what you passed as `--name`)
   * Address: `127.0.0.1` (same machine — no firewall needed)
   * Port: `2083`, API key: the key from step 2, TLS: on (you used
     `--tls selfsigned`)
4. The node row turns green. Create a user, download the `.ovpn`, connect.

## Ports used

| Port | What | Must be reachable from |
|---|---|---|
| 2095 (or yours) | Panel web UI | Only you (your browser) |
| 2083 | Node sync API | Only the panel (`127.0.0.1` here) |
| 1194 | OpenVPN clients | Your users (UDP+TCP opened automatically) |

## Notes

* Data lives in `/var/lib/ovmanager` (panel) and `/var/lib/ovnode` +
  `/etc/openvpn` (node). Back up those paths and you can rebuild anywhere.
* Outgrowing one box? Add remote nodes anytime — see [multi-node](multi-node.md).
  Nothing about the panel install changes.
