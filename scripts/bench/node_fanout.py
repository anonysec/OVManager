#!/usr/bin/env python3
"""Reproduce the node fan-out numbers quoted in CHANGELOG.md 1.0.17 and 1.0.18.

Run from the repository root:

    .venv/bin/python scripts/bench/node_fanout.py            # ~40s, the 3s column
    .venv/bin/python scripts/bench/node_fanout.py --full     # ~7min, both columns

What each measurement backs:

  * the cost table in 1.0.17 — a cycle costs ceil(nodes / workers) x timeout,
    which is why the probe timeout for a known-broken node was cut from 30s
    to 3s;
  * the starvation table in 1.0.18 — a fan-out of unreachable nodes held every
    thread in anyio's shared 40-thread limiter, and ~50 other call sites use
    that pool.

Two traps this script exists to avoid:

  1. A "blackhole" made with a bare ``BaseHTTPRequestHandler`` has no
     ``do_GET``, so it answers **501 immediately**. The client never waits and
     the probe returns instantly. The premise check below fails loudly instead.
  2. A fan-out that is *not* bounded takes ceil(nodes/workers) rounds, so a
     single-node measurement looks fine while the real case is unbounded. Both
     shapes are measured here, and the bounded one is asserted to be bounded.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# 1.0.17's published table, for comparison.
PUBLISHED_COST = {
    (1, 30): 30,
    (8, 30): 64,
    (64, 30): 332,
    (1, 3): 3,
    (8, 3): 6,
    (64, 3): 33,
}
# 1.0.18's published starvation table: (unreachable nodes -> seconds an
# unrelated operation waited) before the shared budget existed.
PUBLISHED_STARVATION = {20: 0.02, 40: 2.95, 80: 6.00}


class _NeverAnswers(BaseHTTPRequestHandler):
    """Accepts the request, then never writes a byte. A real blackhole.

    Do not replace this with a bare BaseHTTPRequestHandler: with no do_GET it
    replies 501 straight away, so every probe "succeeds" in microseconds.
    """

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
        time.sleep(300)

    def log_message(self, *args: object) -> None:
        pass


def start_blackhole() -> int:
    srv = HTTPServer(("127.0.0.1", 0), _NeverAnswers)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def _probe(port: int, timeout: float) -> None:
    """One node RPC against the blackhole, via the real client.

    Deliberately the real client rather than a socket: a bare TCP connect
    completes the moment the server accepts, so it returns instantly and never
    waits out the timeout — the same class of mistake as the 501 blackhole.
    """
    from backend.node.requests import NodeRequests

    client = NodeRequests(address="127.0.0.1", port=port, api_key="bench")
    client.get_sessions(hours=1, timeout=timeout)


def check_premise(port: int, timeout: float = 3.0) -> None:
    """Refuse to measure anything unless a real probe really does block.

    This is trap (1): the first draft measured an instant TCP handshake.
    """
    t0 = time.monotonic()
    _probe(port, timeout)
    waited = time.monotonic() - t0
    if waited < timeout * 0.9:
        raise SystemExit(
            f"PREMISE FAILED: a real probe returned in {waited:.2f}s, expected "
            f"~{timeout}s. Something is answering on that port, so the fan-out "
            "below would cost nothing and every number would be wrong."
        )
    print(f"  premise ok: a real probe blocked for {waited:.1f}s as intended")


def cycle_cost_sync(port: int, nodes: int, timeout: float, workers: int) -> float:
    """One fan-out cycle: `nodes` unreachable nodes, `workers` at a time.

    Synchronous because that is what runs in the panel's threads: a blocking
    socket call in a worker, with the pool width as the only parallelism.
    """
    with ThreadPoolExecutor(max_workers=workers) as pool:
        t0 = time.monotonic()
        futures = [pool.submit(_probe, port, timeout) for _ in range(nodes)]
        for f in futures:
            f.result()
        return time.monotonic() - t0


def measure_cost(port: int, timeouts: list[float], node_counts: list[int], workers: int) -> None:
    print(f"\n=== cycle cost: ceil({node_counts[-1]} / {workers}) rounds of the timeout ===")
    print(f"{'nodes':>6} " + "".join(f"{f'{t}s timeout':>14}" for t in timeouts))
    for n in node_counts:
        row = []
        for t in timeouts:
            took = cycle_cost_sync(port, n, t, workers)
            expected = -(-n // workers) * t
            row.append(f"{took:>8.1f}s (exp {expected:.0f}s)")
        print(f"{n:>6} " + "".join(f"{c:>14}" for c in row))
    print("\n  1.0.17 published, two cores / 6 workers:")
    for n in node_counts:
        cells = "".join(f"{PUBLISHED_COST[(n, t)] / 1:.0f}s".rjust(14) for t in timeouts if (n, t) in PUBLISHED_COST)
        if cells:
            print(f"{n:>6} {cells}")


async def measure_starvation(port: int, nodes: int, timeout: float, workers: int) -> tuple[float, float]:
    """Seconds an unrelated operation waits, with and without the budget.

    "Unbounded" is the pre-1.0.18 shape: node calls straight onto anyio's
    shared limiter with no cap, which is the pool ~50 other call sites use.
    "Bounded" is what the panel does now, behind the shared budget.

    Sampled *while* the fan-out is in flight, and on the same pool the
    unrelated work uses: draining it first on a private executor reported
    0.01s where 1.0.18 published 2.95s.
    """
    from fastapi.concurrency import run_in_threadpool

    from backend.node.fanout import NODE_FANOUT_LIMIT, run_bounded

    def spin() -> None:
        time.sleep(0.01)

    async def unrelated() -> float:
        t0 = time.monotonic()
        await run_in_threadpool(spin)
        return time.monotonic() - t0

    # Unbounded: the pre-1.0.18 fan-out, on the shared pool, no cap.
    inflight = asyncio.gather(*[run_in_threadpool(_probe, port, timeout) for _ in range(nodes)])
    await asyncio.sleep(0.1)  # let it take the pool
    still_running = not inflight.done()
    unbounded = await unrelated()
    await inflight
    if not still_running:
        raise SystemExit(
            "PREMISE FAILED: the unbounded fan-out finished before the unrelated "
            "operation ran, so nothing was in flight to starve it. The numbers "
            "below would be meaningless."
        )

    # Bounded: the shared budget, which is what ships.
    inflight = asyncio.gather(*[run_bounded(_probe, port, timeout) for _ in range(nodes)])
    await asyncio.sleep(0.1)
    still_running = not inflight.done()
    bounded = await unrelated()
    await inflight
    if not still_running:
        raise SystemExit("PREMISE FAILED: the bounded fan-out finished instantly")

    assert NODE_FANOUT_LIMIT < 40, "the cap must stay under anyio's limiter to protect it"
    return unbounded, bounded


async def run_starvation(port: int, timeouts: list[float], node_counts: list[int], workers: int) -> None:
    print("\n=== starvation: an unrelated operation's wait, one probe of an unreachable node ===")
    timeout = timeouts[0]
    print(f"{'nodes':>6} {'unbounded':>12} {'bounded':>10} {'1.0.18 published':>18}")
    for n in node_counts:
        unbounded, bounded = await measure_starvation(port, n, timeout, workers)
        published = PUBLISHED_STARVATION.get(n)
        pub = f"{published:.2f}s" if published is not None else "-"
        print(f"{n:>6} {unbounded:>11.2f}s {bounded:>9.2f}s {pub:>18}")
    print(
        "\n  The published column used 40 nodes on anyio's 40-thread limiter, which\n"
        "  is why it jumped: the fan-out took every thread. The bounded column is\n"
        "  the same work behind backend/node/fanout.py's shared budget."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="also measure the 30s column (about 7 minutes)")
    ap.add_argument("--nodes", default="1,8,64", help="comma-separated node counts (default 1,8,64)")
    ap.add_argument("--skip-starvation", action="store_true")
    ap.add_argument("--only-starvation", action="store_true", help="skip the cycle-cost table")
    args = ap.parse_args()

    os.environ.setdefault("DATA_DIR", "/tmp/ovm-bench-data")
    os.environ.setdefault("OVM_APP_DIR", "/tmp/ovm-bench-data")
    Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

    workers = min(32, (os.cpu_count() or 1) + 4)
    print(f"cpu_count={os.cpu_count()} -> asyncio's default pool is {workers} workers")
    print("a fan-out is served from a pool of that width, so a cycle costs")
    print("ceil(nodes / workers) x timeout; that is the shape every number follows.")

    node_counts = [int(n) for n in args.nodes.split(",")]
    port = start_blackhole()

    timeouts = [3.0, 30.0] if args.full else [3.0]
    print("\n=== checking the premise before measuring anything ===")
    check_premise(port, timeout=3.0)

    if not args.only_starvation:
        measure_cost(port, timeouts, node_counts, workers)
    if not args.skip_starvation:
        asyncio.run(run_starvation(port, timeouts, node_counts, workers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
