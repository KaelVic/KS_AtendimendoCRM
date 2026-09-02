import pytest

from apps.worker.src.pending_jobs import PendingNotificationJob


@pytest.mark.asyncio
async def test_pending_job_delegates_one_dispatch_attempt():
    calls = 0

    async def dispatch():
        nonlocal calls
        calls += 1
        return "SENT"

    job = PendingNotificationJob(dispatch)
    assert await job.run_once() == "SENT"
    assert calls == 1
