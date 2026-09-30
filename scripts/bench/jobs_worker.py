#!/usr/bin/env python3
"""Reproduce the jobs-worker numbers quoted in CHANGELOG.md 1.0.19.

Run from the repository root:

    .venv/bin/python scripts/bench/jobs_worker.py          # about 90 seconds

What it backs:

  * **69.5 MB** — the resident memory the second interpreter costs.
  * **31.8s blocked / 9 ms worst-case /health** — that a scheduled job which
    wedges for a long time no longer stops the panel answering.

The isolation measurement runs the *real* job function
(``check_user_used_traffic``) against a node that accepts the connection and
then never answers, while a real uvicorn serves the panel. A synthetic slow
HTTP server would prove nothing: an earlier version called the job with the
wrong signature and timed a crash, and a "blackhole" with no ``do_GET``
replies 501 at once. The premise checks below fire before anything is reported.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PUBLISHED_MEMORY_MB = 69.5
PUBLISHED_JOB_SECONDS = 31.8
PUBLISHED_WORST_HEALTH_MS = 9.0


def rss_mb(pid: int) -> float:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


class _NeverAnswers(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        time.sleep(300)

    def log_message(self, *args: object) -> None:
        pass


def blackhole() -> int:
    srv = HTTPServer(("127.0.0.1", 0), _NeverAnswers)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def prepare(data_dir: Path) -> None:
    """Create the panel's schema in `data_dir`, in a subprocess.

    In a subprocess because backend.data_paths resolves DATA_DIR at import
    time, and this process may already have imported it against something else.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    script = (
        f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from backend.db.engine import SessionLocal;"
        "from backend.db.migrations import _create_extra_tables, _create_mapped_tables;"
        "db = SessionLocal(); _create_mapped_tables(db); _create_extra_tables(db); db.commit(); db.close()"
    )
    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "DATA_DIR": str(data_dir), "OVM_APP_DIR": str(data_dir)},
        timeout=120,
    )
    if r.returncode != 0:
        raise SystemExit(f"schema creation failed: {r.stderr[-500:]}")


def health(port: int, timeout: float = 10.0) -> tuple[int, float]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout, context=ctx) as r:
            r.read()
            return r.status, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t0
    except Exception:  # noqa: BLE001
        return 0, time.monotonic() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    import tempfile

    data_dir = Path(tempfile.mkdtemp(prefix="ovm-bench-worker-"))
    prepare(data_dir)
    env = {**os.environ, "DATA_DIR": str(data_dir), "OVM_APP_DIR": str(data_dir), "OVM_WORKER": "1"}

    hole = blackhole()
    seed = (
        f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from backend.db.engine import SessionLocal;"
        "from backend.db import crud;"
        "from backend.schema import NodeCreate;"
        "db = SessionLocal();"
        f"crud.create_node(db, NodeCreate(name='dead', address='127.0.0.1', tunnel_address='',"
        f" protocol='udp', ovpn_port=1194, port={hole}, key='k' * 32, use_tls=False,"
        " country_code='DE'), None);"
        "db.commit()"
    )
    r = subprocess.run([sys.executable, "-c", seed], capture_output=True, text=True, env={**env, "OVM_WORKER": "0"}, timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"seeding the unreachable node failed: {r.stderr[-500:]}")

    panel_port = free_port()
    panel = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
            "import uvicorn; from backend.app import api;"
            f"uvicorn.run(api, host='127.0.0.1', port={panel_port}, log_level='error')",
        ],
        cwd=str(REPO_ROOT),
        env={**env, "OVM_WORKER": "0"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            status, _ = health(panel_port, timeout=2)
            if status == 200:
                break
            time.sleep(0.5)
        else:
            raise SystemExit("the panel did not come up")

        print("=== what the second interpreter costs ===")
        panel_rss = rss_mb(panel.pid)
        worker = subprocess.Popen(
            [sys.executable, "-m", "backend.worker"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        lock = data_dir / "scheduler.lock"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not lock.exists():
            time.sleep(0.2)
        if not lock.exists():
            raise SystemExit("the worker never took its lock; refusing to measure")
        time.sleep(3)  # let it finish importing and settle
        worker_rss = rss_mb(worker.pid)
        print(f"  panel process          : {panel_rss:6.1f} MB")
        print(f"  worker process         : {worker_rss:6.1f} MB")
        print(f"  measured               : {worker_rss:6.1f} MB")
        print(f"  1.0.19 published       : {PUBLISHED_MEMORY_MB:6.1f} MB")

        print("\n=== the isolation claim, with the real job against a blackholed node ===")
        status, lat = health(panel_port)
        print(f"  /health before the job : HTTP {status} in {lat * 1000:.0f} ms")

        job = subprocess.Popen(
            [
                sys.executable,
                "-c",
                # Takes no arguments: it opens its own session. Passing one made
                # it raise on the first line, timing a crash rather than a wedge.
                f"import sys, asyncio; sys.path.insert(0, {str(REPO_ROOT)!r});"
                "from backend.operations.billing.daily import check_user_used_traffic;"
                "asyncio.run(check_user_used_traffic()); print('JOB-DONE')",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        worst = 0.0
        samples = 0
        started = time.monotonic()
        while job.poll() is None:
            status, lat = health(panel_port)
            worst = max(worst, lat)
            samples += 1
            time.sleep(0.5)
        out = job.communicate(timeout=60)[0]
        duration = time.monotonic() - started

        if "JOB-DONE" not in (out or ""):
            raise SystemExit(f"the job did not complete, so nothing was measured: {out!r}")
        # Without this the script would "prove" isolation against a job that
        # never blocked, which is how an earlier run was wrong.
        if duration < 8.0:
            raise SystemExit(
                f"PREMISE FAILED: the job only ran {duration:.1f}s, so it never wedged. "
                "Isolation was not exercised and the numbers below would be meaningless."
            )
        print(f"  the job blocked for     : {duration:6.1f}s   (published {PUBLISHED_JOB_SECONDS}s)")
        print("  premise ok              : it blocked, so isolation WAS exercised")
        print(f"  /health sampled         : {samples} times while it ran")
        print(f"  worst /health           : {worst * 1000:6.0f} ms (published {PUBLISHED_WORST_HEALTH_MS:.0f} ms)")
        print(f"  panel stayed responsive : {'YES' if worst < 2.0 and status == 200 else 'NO'}")

        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
        print(f"  worker clean SIGTERM    : exit {worker.returncode}")
    finally:
        panel.terminate()
        try:
            panel.wait(timeout=15)
        except subprocess.TimeoutExpired:
            panel.kill()
        shutil.rmtree(data_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
