"""The shared node fan-out budget.

Node calls block on socket timeouts, so an unbounded fan-out takes threads
out of pools the rest of the application needs. On a two-core box, eight
unrelated operations that take 40ms normally took 2.95s while 40
unreachable nodes were being probed, because the fan-out held every thread
in anyio's shared 40-thread limiter — which 50-odd other call sites use.

These tests pin the bound that prevents it.
"""

import asyncio
import os
import threading
import time

import pytest
from fastapi.concurrency import run_in_threadpool

from backend.node import diagnostics, fanout


def test_budget_cannot_reach_anios_limiter():
    """The cap only protects the shared pool while it stays a fraction of it.

    anyio's default limiter is 40 threads; a cap at or above that can starve
    every other run_in_threadpool caller in the application.
    """
    assert 1 <= fanout.NODE_FANOUT_LIMIT < 40


def test_background_budget_leaves_room_for_the_scheduled_jobs():
    """The collector shares a small pool with the backup and alert jobs.

    asyncio's default executor is min(32, cpu_count + 4) — six workers on a
    two-core box — and the collector must not be able to take all of them.
    A fixed number, not a share: the pool width scales with cpu_count, and
    the constraint is leaving room on any machine.
    """
    pool_width = min(32, (os.cpu_count() or 1) + 4)
    assert 1 <= fanout.BACKGROUND_FANOUT_LIMIT < pool_width or pool_width > 40


@pytest.mark.asyncio
async def test_page_render_fanout_respects_the_shared_cap(monkeypatch):
    """Regression: the user-list fan-out was unbounded.

    It runs inside a page render, so it multiplied on every request — and it
    was the path that actually took the shared pool.
    """
    nodes = [f"n{i}" for i in range(60)]
    state = {"in_flight": 0, "max": 0}
    lock = asyncio.Lock()

    class FakeClient:
        def __init__(self, node):
            self.node = node

        def get_sessions(self, hours=None, timeout=None):
            return {}

    async def counting_run_in_threadpool(fn, *args):
        # fanout.run_bounded resolves this name at call time, so patching it
        # here instruments exactly the path the panel takes.
        async with lock:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
        try:
            await asyncio.sleep(0.01)
            return fn(*args)
        finally:
            async with lock:
                state["in_flight"] -= 1

    monkeypatch.setattr(diagnostics, "node_client", lambda n, **kw: FakeClient(n))
    monkeypatch.setattr(diagnostics.crud, "get_active_nodes", lambda db: nodes)
    monkeypatch.setattr(diagnostics.crud, "get_user_id_name_pairs", lambda db: [])
    monkeypatch.setattr("fastapi.concurrency.run_in_threadpool", counting_run_in_threadpool)

    await diagnostics.get_active_connection_counts(object())

    assert state["max"] <= fanout.NODE_FANOUT_LIMIT, (
        f"fan-out reached {state['max']} concurrent node calls, cap is {fanout.NODE_FANOUT_LIMIT}"
    )
    assert state["max"] > 1, "the fan-out should stay concurrent, not serialised"


@pytest.mark.asyncio
async def test_background_fanout_respects_its_own_cap():
    # gather_background runs callables with asyncio.to_thread, so these are
    # blocking functions like the node RPCs it exists for — hence threading.Lock.
    state = {"in_flight": 0, "max": 0}
    lock = threading.Lock()

    def probe():
        with lock:
            state["in_flight"] += 1
            state["max"] = max(state["max"], state["in_flight"])
        try:
            time.sleep(0.05)
        finally:
            with lock:
                state["in_flight"] -= 1

    await fanout.gather_background([probe] * 40)

    assert state["max"] <= fanout.BACKGROUND_FANOUT_LIMIT
    assert state["max"] > 1, "the collector should stay concurrent"


@pytest.mark.asyncio
async def test_unrelated_work_is_not_starved_by_a_node_fanout():
    """The user-visible symptom, asserted directly rather than inferred."""

    async def unrelated():
        t0 = time.monotonic()
        await run_in_threadpool(time.sleep, 0.01)
        return time.monotonic() - t0

    baseline = await unrelated()
    assert baseline < 0.5, f"baseline is already slow: {baseline:.2f}s"

    def blocking_node_call():
        time.sleep(0.2)  # stands in for a node RPC waiting out its timeout

    fanout_task = asyncio.gather(*[fanout.run_bounded(blocking_node_call) for _ in range(60)])
    await asyncio.sleep(0.05)  # let the fan-out take its share of the pool

    starved = await unrelated()
    await fanout_task

    assert starved < 0.5, f"unrelated work waited {starved:.2f}s behind a node fan-out (baseline {baseline:.3f}s)"


# ── the request deadline ──────────────────────────────────────────────────
#
# 1.0.33. gather_nodes runs inside request handlers, and it used to wait for
# every node however dead they were.


def test_gather_nodes_returns_by_the_deadline_not_when_the_last_node_answers():
    """A request must not wait on a dead node.

    One unreachable node cost 30.1s of page load before this, and eighty cost
    66.2s. The 3s probe timeout only applies to a node *already
    recorded* broken, which cannot happen before it has been tried — so a node
    added a moment ago is always a 30s node, and a misconfigured one hangs the
    whole user list.
    """
    calls = [lambda: time.sleep(30) for _ in range(4)]

    async def go():
        t0 = time.monotonic()
        results = await fanout.gather_nodes(calls, deadline=0.5)
        return time.monotonic() - t0, results

    took, results = asyncio.run(go())
    assert took < 5, f"waited {took:.1f}s for nodes that never answer"
    assert len(results) == 4
    assert all(isinstance(r, fanout.FanoutDeadline) for r in results)


def test_unfinished_calls_arrive_as_exceptions_so_existing_guards_still_work():
    """Every caller already did ``isinstance(item, Exception)`` and skipped.

    That is how all of them handled an unreachable node, so returning anything
    else would raise TypeError inside a page render instead of quietly skipping
    one node. Returning a real exception keeps the result list aligned with the
    node list by position as well.
    """
    calls = [lambda: "answered", lambda: time.sleep(30)]

    async def go():
        return await fanout.gather_nodes(calls, deadline=0.5)

    results = asyncio.run(go())
    assert results[0] == "answered"
    assert isinstance(results[1], fanout.FanoutDeadline)
    assert isinstance(results[1], Exception), "callers filter on Exception, not on this type"


def test_a_call_that_raises_still_comes_back_as_its_own_exception():
    """The deadline must not swallow or replace a real failure."""

    def boom():
        raise ValueError("node said no")

    async def go():
        return await fanout.gather_nodes([boom], deadline=5)

    (result,) = asyncio.run(go())
    assert isinstance(result, ValueError), result


def test_fast_nodes_are_unaffected_by_the_deadline():
    """The deadline exists for dead nodes; a healthy fleet must not notice."""

    # Bound as a default, not closed over: a bare `lambda: i` would have all
    # thirty see the final value.
    calls = [(lambda _i=i: _i) for i in range(30)]

    async def go():
        t0 = time.monotonic()
        results = await fanout.gather_nodes(calls)
        return time.monotonic() - t0, results

    took, results = asyncio.run(go())
    assert results == list(range(30))
    assert took < 1, f"30 instant calls took {took:.2f}s"


def test_the_deadline_is_long_enough_for_a_healthy_fleet():
    """Guard the choice of 10s against a fleet that legitimately needs more.

    A healthy fleet on a two-core box at 50ms per node: 20 nodes 1.7s, 80
    nodes 4.1s. The deadline has to clear those comfortably, or the fix trades
    one slow page for truncated data.
    """
    assert fanout.REQUEST_FANOUT_DEADLINE >= 5.0, "below the measured 80-node healthy case"
    assert fanout.REQUEST_FANOUT_DEADLINE <= 30.0, "a page load cannot usefully wait a minute"


def test_abandoned_calls_keep_their_budget_slot():
    """They are not cancelled, and that is deliberate.

    The work is already inside a blocking thread that cancellation cannot reach.
    Dropping the await would release the semaphore slot while that thread is
    still occupied, putting back exactly the starvation this module exists to
    prevent — so a timed-out fan-out must keep counting against the budget.
    """
    started = threading.Event()

    def slow():
        started.set()
        time.sleep(2)

    async def go():
        t0 = time.monotonic()
        await fanout.gather_nodes([slow], deadline=0.3)
        return time.monotonic() - t0

    took = asyncio.run(go())
    assert took < 1.5, "the deadline did not cut the wait short"
    assert started.is_set(), "the call never reached its thread"
    # The abandoned task is still running, so the budget is still committed.
    time.sleep(2.2)


def test_background_fanout_has_no_deadline():
    """The periodic collector can wait as long as it needs.

    It is not a request: nothing is waiting on a page render, and a backup that
    gives up early is worse than one that finishes. Only gather_nodes is bounded.
    """
    assert not hasattr(fanout, "BACKGROUND_FANOUT_DEADLINE")
    calls = [lambda: time.sleep(0.2) for _ in range(3)]

    async def go():
        t0 = time.monotonic()
        results = await fanout.gather_background(calls)
        return time.monotonic() - t0, results

    took, results = asyncio.run(go())
    assert all(r is None for r in results)
    assert took >= 0.2
