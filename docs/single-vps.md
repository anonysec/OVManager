# All-in-one: panel + node on one VPS

This is the easiest topology: one server runs everything. Good for personal
use and small teams.

## Steps

1. Install the panel ([quickstart](quickstart.md)). At the end, the green
   **Ready** card prints a **node install command** that already contains an
   API key, for example:

   ```bash
   curl -sSL https://anonysec.github.io/OVNode/install.sh \
     | sudo bash -s -- install -y --name node-1 --tls selfsigned \
       --api-key 'PASTE-GENERATED-KEY'
   ```

2. Run that command on the **same server**. It installs the OVNode agent +
   OpenVPN (about 2–3 minutes) and prints a green summary including the key.
3. Back in the panel: **Nodes → Add Node** and fill in:
   * Name: `node-1` (must match exactly what you passed as `--name`)
   * Address: `127.0.0.1` (same machine — no firewall needed)
   * Port: `2083`, API key: the key from step 1, TLS: on (you used
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
