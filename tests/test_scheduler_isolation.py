import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import backend.scheduler as scheduling


def test_job_ids_are_unambiguous_and_separate_execution_jobs():
    pairs = [("a-b", "c"), ("a", "b-c"), ("exec-a", "b"), ("a", "b"), ("a", 'b", "c')]
    ids = [fn(*pair) for fn in (scheduling._cron_job_id, scheduling._range_execution_job_id) for pair in pairs]
    assert len(set(ids)) == len(ids)


@pytest.mark.asyncio
async def test_register_update_and_remove_do_not_touch_other_account(monkeypatch):
    scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop(), timezone="UTC")
    scheduler.start(paused=True)
    monkeypatch.setattr(scheduling, "scheduler", scheduler)
    monkeypatch.setattr(scheduling, "_update_next_scheduled_at", lambda *args: None)
    try:
        scheduling.add_or_update_sign_task_job("a-b", "c", "09:00")
        scheduling.add_or_update_sign_task_job("a", "b-c", "10:00")
        for pair in [("a-b", "c"), ("a", "b-c")]:
            scheduling._schedule_range_execution(*pair, datetime.now(timezone.utc) + timedelta(hours=1))
        assert len(scheduler.get_jobs()) == 4
        scheduling.add_or_update_sign_task_job("a-b", "c", "11:00")
        scheduling.remove_sign_task_job("a-b", "c")
        remaining = scheduler.get_jobs()
        assert len(remaining) == 2
        assert all(job.args == ("a", "b-c") for job in remaining)
    finally:
        scheduler.shutdown(wait=False)


def test_cron_uses_configured_timezone(monkeypatch):
    monkeypatch.setattr(scheduling, "_get_scheduler_timezone", lambda: ZoneInfo("Asia/Shanghai"))
    trigger = scheduling.create_cron_trigger("09:00")
    fire = trigger.get_next_fire_time(None, datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert fire.astimezone(timezone.utc).hour == 1
