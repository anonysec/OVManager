#!/usr/bin/env python3
"""Reproduce the request fan-out numbers quoted in CHANGELOG.md 1.0.33.

Run from the repository root:

    .venv/bin/python scripts/bench/request_fanout.py           # ~4 minutes
    .venv/bin/python scripts/bench/request_fanout.py --dead-only

What it backs
-------------

`gather_nodes` runs inside request handlers -- the user list is the one that
matters -- and it used to wait for every node however dead they were. The
numbers below are why that was a ceiling worth naming rather than a limit worth
documenting:

  * a **single** newly-added unreachable node cost 30.1s of page load, because
    the short 3s probe timeout only applies once a node has been *recorded*
    broken, which cannot happen before it has been tried;
  * 80 of them cost 66.2s;
  * the healthy fleet has to stay well clear of whatever deadline replaces that,
    which is the other half of the measurement and the reason this script
    measures both.

Premises, all checked below
---------------------------

Every measurement in this repository was wrong at least once while it was
written, and this one started wrong in a way worth recording: `DATA_DIR` is
resolved at **import time** (`backend/data_paths.py:8`), so setting it only in
the environment handed to a seeding subprocess leaves the measuring process
reading a different database. The first draft of this script reported a flat
18.1s for every node count while quietly probing 118 leftover rows from
`OVManager/data` instead of the nodes it had just seeded. Hence
`_assert_premises` below, which fails rather than reports.

Two more, both load-bearing:

  * **not every node is probed.** Past the deadline the budget's semaphore is
    still full, so some nodes never start. Asserting that all N were probed
    fails on a correct implementation.
  * **abandoned work still holds its budget slot.** A fan-out that times out
    leaves its calls running, and they keep the semaphore until the thread
    returns. That is correct — the thread really is occupied, and releasing the
    slot early would put back the starvation 1.0.18 fixed — but it means a
    benchmark loop's later iterations start with fewer free slots than the
    first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Must precede every backend import: DATA_DIR is read at import time.
_DATA = Path(tempfile.mkdtemp(prefix="ovm-bench-fanout-"))
os.environ["DATA_DIR"] = str(_DATA)
os.environ["OVM_APP_DIR"] = str(_DATA)
os.environ["OVM_WORKER"] = "0"

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import backend.data_paths as _dp  # noqa: E402

POOL_WIDTH = min(32, (os.cpu_count() or 1) + 4)
HEALTHY_LATENCY = 0.05  # seconds, per node; a realistic WAN node
NODE_COUNTS = (1, 8, 20, 80, 200)

# 1.0.33 published. Measured on two cores, so a six-thread pool.
PUBLISHED_DEAD = {1: 30.1, 8: 30.1, 20: 30.1, 80: 66.2}
PUBLISHED_HEALTHY = {1: 0.08, 8: 1.12, 20: 1.74, 80: 4.15, 200: 11.49}


class _NeverAnswers(BaseHTTPRequestHandler):
    """Accepts, then never writes. A real blackhole, not a 501."""

    def do_GET(self) -> None:  # noqa: N802
        time.sleep(300)

    def log_message(self, *args: object) -> None:
        pass


class _Answers(BaseHTTPRequestHandler):
    def __init__(self, *a: object, **kw: object) -> None:
        self._body = json.dumps({"live_sessions": [{"common_name": "c1"}], "total_sessions": 1}).encode()
        super().__init__(*a, **kw)

    def do_GET(self) -> None:  # noqa: N802
        time.sleep(HEALTHY_LATENCY)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self._body)))
            self.end_headers()
            self.wfile.write(self._body)
        except (BrokenPipeError, ConnectionResetError):
            # The request gave up at the deadline and went away mid-write, which
            # is the behaviour being measured. Not an error worth printing.
            pass

    def log_message(self, *args: object) -> None:
        pass


def _serve(handler) -> int:
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def _assert_premises() -> None:
    """The one thing checkable before anything is seeded.

    This is the premise that actually bit: DATA_DIR is resolved at import time,
    so a measuring process whose environment was only set for the seeding
    subprocess reads a different database entirely. The per-iteration checks
    live in `_measure`, where there are nodes to check.
    """
    if _dp.DATA_DIR != _DATA:
        raise SystemExit(
            f"PREMISE FAILED: backend resolved DATA_DIR={_dp.DATA_DIR}, not {_DATA}. "
            "It is read at import time, so it must be set in this process, not only "
            "in the environment handed to a subprocess."
        )
    print(f"  premise ok: DATA_DIR={_DATA} (resolved at import, not inherited)")


async def _measure(handler, counts: tuple[int, ...], db) -> dict[int, float]:
    from backend.db import crud
    from backend.db.models import Node
    from backend.node import diagnostics
    from backend.schema import NodeCreate

    port = _serve(handler)
    out: dict[int, float] = {}
    for n in counts:
        db.query(Node).delete()
        db.commit()
        for i in range(n):
            crud.create_node(
                db,
                NodeCreate(
                    name=f"n{i}",
                    address="127.0.0.1",
                    tunnel_address="",
                    protocol="udp",
                    ovpn_port=1194,
                    port=port,
                    key="k" * 32,
                    use_tls=False,
                    country_code="DE",
                ),
                None,
            )
        db.commit()

        seeded = crud.get_active_nodes(db)
        if len(seeded) != n:
            raise SystemExit(f"PREMISE FAILED: seeded {n}, get_active_nodes returned {len(seeded)}")
        if any(x.address != "127.0.0.1" or x.port != port for x in seeded):
            raise SystemExit("PREMISE FAILED: the seeded set contains a node this script did not create")

        probed: list[int] = []
        original = diagnostics.node_client

        def spy(node, _probed=probed, _original=original):
            _probed.append(node.id)
            return _original(node)

        diagnostics.node_client = spy
        try:
            t0 = time.monotonic()
            await diagnostics.get_active_connection_counts(db)
            took = time.monotonic() - t0
        finally:
            diagnostics.node_client = original

        # Not `== n`: past the deadline the semaphore is still full and some
        # nodes never start. That is the fix working, not a broken premise.
        if len(probed) > n:
            raise SystemExit(f"PREMISE FAILED: probed {len(probed)} nodes but only seeded {n}")
        out[n] = took
    return out


def _table(title: str, measured: dict[int, float], published: dict[int, float]) -> None:
    print(f"\n=== {title} ===")
    print(f"{'nodes':>6} {'measured':>10} {'1.0.33 published':>18}")
    for n, took in measured.items():
        was = f"{published[n]:.1f}s" if n in published else "-"
        print(f"{n:>6} {took:>9.2f}s {was:>18}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dead-only", action="store_true")
    args = ap.parse_args()

    from backend.db.engine import SessionLocal
    from backend.db.migrations import _create_extra_tables, _create_mapped_tables
    from backend.node.fanout import REQUEST_FANOUT_DEADLINE

    db = SessionLocal()
    _create_mapped_tables(db)
    _create_extra_tables(db)
    db.commit()

    print(f"cpu_count={os.cpu_count()} -> asyncio's default pool is {POOL_WIDTH} workers")
    print(f"request fan-out deadline: {REQUEST_FANOUT_DEADLINE:g}s")
    print("\n=== checking the premises before measuring anything ===")
    _assert_premises()

    dead = asyncio.run(_measure(_NeverAnswers, NODE_COUNTS, db))
    _table("unreachable nodes, one page render", dead, PUBLISHED_DEAD)
    print(
        "\n  Before the deadline these were 30.1s, 30.1s, 30.1s and 66.2s: a node that\n"
        "  has just been added costs the full 30s, because the 3s probe timeout only\n"
        "  applies once a node has been recorded broken."
    )

    if not args.dead_only:
        healthy = asyncio.run(_measure(_Answers, NODE_COUNTS, db))
        _table(f"healthy nodes at {HEALTHY_LATENCY * 1000:.0f}ms each", healthy, PUBLISHED_HEALTHY)
        print(
            "\n  These must not move: the deadline exists for dead nodes, and a healthy\n"
            "  fleet that got slower would be a regression dressed as a fix. The one\n"
            "  that does change is 200, which now returns partial counts at the\n"
            "  deadline instead of waiting — the trade 1.0.33 names explicitly."
        )

    db.close()
    import shutil

    shutil.rmtree(_DATA, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
