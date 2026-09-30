"""One shared bound on how many node RPCs may be in flight at once.

Node calls block on socket timeouts, so a fan-out of unreachable nodes
holds a thread for the whole timeout. Sharing the application's thread pool
with them means a large enough fan-out takes every thread in it and
everything else that needs a thread waits behind them: one dead-node sweep
turned eight unrelated 53ms operations into 2.95s.

ops.py bounded its own fan-outs at 20; that limit was never applied to the
fan-outs that run on a page render, which is where the multiplication
actually happens. It lives here now so every site shares one budget.
"""

import asyncio

# Half of anyio's 40-thread limiter, so node RPCs can never take all of it.
NODE_FANOUT_LIMIT = 20

_semaphore: asyncio.Semaphore | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _fanout() -> asyncio.Semaphore:
    """The fan-out semaphore for the running event loop.

    Rebuilt when the loop changes, because an asyncio primitive belongs to
    the loop that created it and the panel runs a fresh one on restart.
    """
    global _semaphore, _loop
    loop = asyncio.get_running_loop()
    if _loop is not loop:
        _semaphore = asyncio.Semaphore(NODE_FANOUT_LIMIT)
        _loop = loop
    return _semaphore


async def run_bounded(fn, *args):
    """Run one blocking node call in the threadpool under the shared cap."""
    async with _fanout():
        from fastapi.concurrency import run_in_threadpool

        return await run_in_threadpool(fn, *args)


# A request that renders a page must not wait on every node, however many there
# are or however dead they are. The worst case is a node just added and
# unreachable: the short 3s timeout only applies once a node has been *recorded*
# as broken, which cannot happen before it has been tried, so one misconfigured
# node made the whole user list take half a minute.
#
# 10s sits above the healthy cases that matter and below the pathological ones.
# Past roughly a hundred healthy nodes the request returns partial counts
# instead of waiting, and the background collector — which has no deadline —
# fills in the rest within one cycle.
REQUEST_FANOUT_DEADLINE = 10.0


class FanoutDeadline(Exception):
    """A node did not answer before the request's fan-out deadline.

    An Exception so that every caller's existing ``isinstance(item, Exception)``
    guard skips it unchanged — that is how all of them already handled a node
    that could not be reached, and it keeps the result list aligned with the
    node list by position.
    """


# Tasks still running past the deadline. Held so they are not garbage collected
# mid-flight: a task collected while awaiting a threadpool call can take the
# thread's result with it.
_inflight: set = set()


def _abandon(task) -> None:
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def gather_nodes(calls, deadline: float = REQUEST_FANOUT_DEADLINE):
    """Run a fan-out of node calls under the shared cap, bounded in total time.

    Returns one result per call, in order. Anything that finished is its value,
    anything that raised is the exception, and anything still running when the
    deadline passed is a :class:`FanoutDeadline`.

    Unfinished calls are deliberately *not* cancelled. The work is already
    inside a blocking thread that cancellation cannot reach, and dropping the
    await would release its semaphore slot while that thread is still occupied,
    breaking the cap this module exists to enforce.
    """
    tasks = [asyncio.ensure_future(run_bounded(fn)) for fn in calls]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=deadline)
    for task in pending:
        _abandon(task)
    results = []
    for task in tasks:
        if task in pending:
            results.append(FanoutDeadline(f"no answer within {deadline:g}s"))
        elif task.cancelled():
            results.append(FanoutDeadline("cancelled"))
        else:
            exc = task.exception()
            results.append(exc if exc is not None else task.result())
    return results


# The live collector runs on asyncio's default executor, which is where the
# scheduled jobs live too: create_panel_backup, push_offsite,
# send_backup_document, run_daily_alerts, and the two prunes. That pool is
# min(32, cpu_count + 4) — six workers on a two-core box — so probing every
# node can take all of them and a backup stops running.
#
# Deliberately a fixed number rather than a share of the pool: the pool's
# width scales with cpu_count, and what matters is leaving room for the
# scheduled work on any machine.
BACKGROUND_FANOUT_LIMIT = 4

_background: asyncio.Semaphore | None = None
_background_loop: asyncio.AbstractEventLoop | None = None


def _background_fanout() -> asyncio.Semaphore:
    global _background, _background_loop
    loop = asyncio.get_running_loop()
    if _background_loop is not loop:
        _background = asyncio.Semaphore(BACKGROUND_FANOUT_LIMIT)
        _background_loop = loop
    return _background


async def run_background(fn, *args):
    """Run one blocking node call for the periodic collector, under its cap."""
    async with _background_fanout():
        return await asyncio.to_thread(fn, *args)


async def gather_background(calls):
    """Fan out the collector's probes without taking the whole default pool."""
    return await asyncio.gather(*[run_background(fn) for fn in calls], return_exceptions=True)
