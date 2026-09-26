"""Node-down / node-recovery Telegram alerts.

Fed by the 5-minute metrics collector: every tick passes its node snapshot
rows to :func:`check_node_alerts`, which compares each node's ``reachable``
flag with the remembered state and messages the owner once per outage.

Design notes
------------
* State is in-memory only. A panel restart forgets it, so the first tick
  after a restart only seeds state and never alerts — no restart spam.
* An outage is announced once: a node still down on later ticks is not
  re-announced, but a *failed* send is retried on the next tick (nothing
  marks the outage announced until Telegram accepts the message).
* A per-node cooldown keeps a flapping node from paging the owner every
  5 minutes: a DOWN alert within the window after the previous one is
  dropped (the flap up in between stays quiet too, since it was never
  announced).
* All sending goes through ``notifier.send_telegram``: it no-ops when the
  bot is disabled or unconfigured and never raises.
"""

from __future__ import annotations

import time

from backend.logger import logger
from backend.operations.notifier import send_telegram

DOWN_ALERT_COOLDOWN_SECONDS = 30 * 60

_node_state: dict[int, bool] = {}
_last_down_alert: dict[int, float] = {}
_alerted_down: set[int] = set()


def check_node_alerts(rows: list[dict], *, notify: bool = True, now: float | None = None) -> int:
    """Compare this tick's reachable flags with the remembered state.

    ``rows`` are the collector's snapshot rows (``node_id``, ``node_name``,
    ``reachable``). State is always updated — even when ``notify`` is off —
    so re-enabling alerts later does not replay stale transitions; an
    ongoing outage is still announced once when alerts get re-enabled.
    Returns the number of Telegram messages sent. Never raises.
    """
    sent = 0
    ts = time.time() if now is None else now
    try:
        for row in rows:
            node_id = int(row.get("node_id") or 0)
            if not node_id:
                continue
            name = str(row.get("node_name") or f"node-{node_id}")
            reachable = bool(row.get("reachable"))
            prev = _node_state.get(node_id)
            _node_state[node_id] = reachable

            if prev is None:
                continue  # first tick after start: seed only

            if not reachable:
                if node_id in _alerted_down:
                    continue  # outage already announced
                if not notify:
                    continue
                if ts - _last_down_alert.get(node_id, 0.0) < DOWN_ALERT_COOLDOWN_SECONDS:
                    continue  # flapping: stay quiet, retry after the window
                if send_telegram(f"🔴 Node {name} is unreachable."):
                    _last_down_alert[node_id] = ts
                    _alerted_down.add(node_id)
                    sent += 1
            elif node_id in _alerted_down:
                _alerted_down.discard(node_id)
                if notify and send_telegram(f"🟢 Node {name} is back online."):
                    sent += 1
    except Exception as exc:
        logger.error("Node alerts check failed (%s)", type(exc).__name__)
    return sent
