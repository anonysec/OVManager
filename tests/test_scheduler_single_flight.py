"""Single-flight: a periodic job never runs twice at once."""

import asyncio

import pytest

from backend.scheduler import _running, single_flight


@pytest.fixture(autouse=True)
def _clean_running():
    _running.clear()
    yield
    _running.clear()


@pytest.mark.asyncio
async def test_second_fire_skips_while_first_run_is_in_flight():
    calls: list[int] = []
    release = asyncio.Event()

    async def body():
        calls.append(1)
        await release.wait()
        return "done"

    guarded = single_flight(body)

    first = asyncio.create_task(guarded())
    await asyncio.sleep(0)  # let the first run reach its await

    second = await guarded()
    assert second is None, "a run fired while the first is in flight must be skipped"
    assert len(calls) == 1, f"body must run exactly once, ran {len(calls)} times"

    release.set()
    assert await first == "done"
    assert len(calls) == 1

    await guarded()
    assert len(calls) == 2, "guard must release after the run finishes"


@pytest.mark.asyncio
async def test_guard_releases_after_a_crash():
    calls: list[int] = []

    async def body():
        calls.append(1)
        raise RuntimeError("boom")

    guarded = single_flight(body)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await guarded()

    assert len(calls) == 2, "a crashed run must not keep the guard latched"


def test_worker_registers_the_four_heavy_jobs_with_guards():
    from apscheduler.schedulers.background import BackgroundScheduler

    from backend.operations.billing.daily import check_user_used_traffic, enforce_user_limits
    from backend.operations.observability.metrics import collect_metrics
    from backend.scheduler import auto_prune_audit_job
    from backend.worker import register_worker_jobs

    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    register_worker_jobs(scheduler)
    guarded = {
        "check_user_used_traffic": check_user_used_traffic,
        "enforce_user_limits": enforce_user_limits,
        "collect_metrics": collect_metrics,
        "auto_prune_audit_job": auto_prune_audit_job,
    }
    for job_id, original in guarded.items():
        func = scheduler.get_job(job_id).func
        assert func is not original, f"{job_id} must be wrapped in the single-flight guard"
        assert func.__name__ == job_id, f"{job_id} id must be preserved"
