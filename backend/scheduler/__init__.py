from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

scheduler: AsyncIOScheduler | None = None


def create_cron_trigger(cron_str: str) -> CronTrigger:
    """自动解析格式并创建 CronTrigger，支持 5位和6位 cron 表达式以及 HH:MM 或 HH:MM:SS"""
    if ":" in cron_str:
        parts = cron_str.split(":")
        try:
            if len(parts) == 2:
                hour, minute = parts
                cron_str = f"0 {int(minute)} {int(hour)} * * *"
            elif len(parts) == 3:
                hour, minute, second = parts
                cron_str = f"{int(second)} {int(minute)} {int(hour)} * * *"
        except ValueError:
            pass

    parts = cron_str.split()
    if len(parts) == 6:
        return CronTrigger(
            second=parts[0],
            minute=parts[1],
            hour=parts[2],
            day=parts[3],
            month=parts[4],
            day_of_week=parts[5],
        )
    return CronTrigger.from_crontab(cron_str)


def _get_scheduler_logger() -> logging.Logger:
    return logging.getLogger("backend.scheduler")


def _get_scheduler_timezone() -> ZoneInfo:
    from backend.core.config import get_settings

    settings = get_settings()
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        return ZoneInfo("UTC")


def _parse_range_datetime(value: str, now: datetime) -> datetime | None:
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            return now.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=parsed.second,
                microsecond=0,
            )
        except ValueError:
            continue
    return None


def _parse_range_window(
    range_start_str: str, range_end_str: str, now: datetime
) -> tuple[datetime, datetime] | None:
    start_dt = _parse_range_datetime(range_start_str, now)
    end_dt = _parse_range_datetime(range_end_str, now)
    if start_dt is None or end_dt is None:
        return None
    if end_dt < start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def _parse_last_run_time(last_run: dict | None) -> datetime | None:
    if not isinstance(last_run, dict):
        return None
    raw = last_run.get("time")
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _has_run_on_local_day(last_run: dict | None, now: datetime, tz: ZoneInfo) -> bool:
    last_run_dt = _parse_last_run_time(last_run)
    if last_run_dt is None:
        return False
    return last_run_dt.astimezone(tz).date() == now.date()


def _cron_job_id(account_name: str, task_name: str) -> str:
    return f"sign-{account_name}-{task_name}"


def _range_execution_job_id(account_name: str, task_name: str) -> str:
    return f"sign-exec-{account_name}-{task_name}"


def _parse_scheduled_time(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _refresh_tasks_cache() -> None:
    from backend.services.sign_tasks import get_sign_task_service

    try:
        get_sign_task_service().list_tasks(force_refresh=True)
    except Exception:
        pass


def _update_next_scheduled_at(
    task_name: str, account_name: str, next_scheduled_at: datetime | None
) -> None:
    from backend.repositories.sign_task_config_repo import get_sign_task_config_repo

    config_repo = get_sign_task_config_repo()
    config_repo.update_next_scheduled_at(task_name, account_name, next_scheduled_at)
    _refresh_tasks_cache()


def _clear_next_scheduled_at(task_name: str, account_name: str) -> None:
    _update_next_scheduled_at(task_name, account_name, None)


def _schedule_range_execution(
    account_name: str,
    task_name: str,
    actual_run_time: datetime,
) -> None:
    logger = _get_scheduler_logger()
    if scheduler is None:
        return

    job_id = _range_execution_job_id(account_name, task_name)
    scheduler.add_job(
        _execute_sign_task,
        trigger=DateTrigger(run_date=actual_run_time),
        id=job_id,
        args=[account_name, task_name],
        replace_existing=True,
    )
    _update_next_scheduled_at(
        task_name,
        account_name,
        actual_run_time.astimezone(UTC),
    )
    logger.info(
        "Scheduler: 已登记一次性执行任务 id=%s run_at=%s",
        job_id,
        actual_run_time.isoformat(),
    )


async def _execute_sign_task(account_name: str, task_name: str) -> None:
    """实际执行签到任务"""
    from backend.services.sign_tasks import get_sign_task_service

    logger = _get_scheduler_logger()
    try:
        _clear_next_scheduled_at(task_name, account_name)
        logger.info(f"Scheduler: 开始执行签到任务 {task_name} (账号: {account_name})")
        sign_task_service = get_sign_task_service()
        result = await sign_task_service.run_task_with_logs(account_name, task_name)
        if result.get("success"):
            logger.info(f"Scheduler: 任务 {task_name} 执行成功")
        else:
            logger.error(f"Scheduler: 任务 {task_name} 执行失败: {result.get('error')}")
    except Exception as e:
        logger.error(f"Scheduler: 执行签到任务 {task_name} 失败: {e}", exc_info=True)


async def _job_run_sign_task(
    account_name: str, task_name: str, skip_range_delay: bool = False
) -> None:
    """运行签到任务的 Job 包装器 - 重构为预计算调度时间"""
    from backend.services.sign_tasks import get_sign_task_service

    logger = _get_scheduler_logger()
    try:
        sign_task_service = get_sign_task_service()
        task_config = sign_task_service.get_task(task_name, account_name)

        if not task_config:
            logger.warning(f"Scheduler: 任务 {task_name} (账号: {account_name}) 配置不存在")
            return

        if not skip_range_delay and task_config.get("execution_mode") == "range":
            range_start_str = task_config.get("range_start")
            range_end_str = task_config.get("range_end")
            existing_scheduled_at = _parse_scheduled_time(task_config.get("next_scheduled_at"))
            now_utc = datetime.now(UTC)

            if existing_scheduled_at and existing_scheduled_at > now_utc:
                if scheduler and scheduler.get_job(_range_execution_job_id(account_name, task_name)):
                    logger.info(
                        "Scheduler: 任务 %s 已存在预计执行时间 %s，跳过重新随机",
                        task_name,
                        existing_scheduled_at.isoformat(),
                    )
                    return

            if range_start_str and range_end_str:
                try:
                    tz = _get_scheduler_timezone()
                    now = datetime.now(tz)
                    window = _parse_range_window(range_start_str, range_end_str, now)

                    if window is not None:
                        start_dt, end_dt = window
                        total_seconds = (end_dt - start_dt).total_seconds()

                        if total_seconds > 0:
                            random_offset = random.uniform(0, total_seconds)
                            actual_run_time = start_dt + timedelta(seconds=random_offset)
                            _schedule_range_execution(account_name, task_name, actual_run_time)
                            logger.info(
                                f"Scheduler: 任务 {task_name} 已调度到 {actual_run_time.strftime('%H:%M:%S')} "
                                f"(窗口: {range_start_str} - {range_end_str}, 延迟: {int(random_offset)}秒)"
                            )
                            return
                except Exception as e:
                    logger.error(f"Scheduler: 预计算调度时间失败: {e}，将立即执行", exc_info=True)

        await _execute_sign_task(account_name, task_name)

    except Exception as e:
        logger.error(f"Scheduler: 运行签到任务 {task_name} 失败: {e}", exc_info=True)


async def _restore_pending_range_jobs(sign_tasks: list[dict]) -> None:
    tz = _get_scheduler_timezone()
    logger = _get_scheduler_logger()
    now_utc = datetime.now(UTC)

    for st in sign_tasks:
        if not st.get("enabled", True) or st.get("execution_mode") != "range":
            continue

        scheduled_at = _parse_scheduled_time(st.get("next_scheduled_at"))
        if scheduled_at is None:
            continue

        if scheduled_at <= now_utc:
            _clear_next_scheduled_at(st["name"], st["account_name"])
            continue

        if _has_run_on_local_day(st.get("last_run"), now_utc.astimezone(tz), tz):
            _clear_next_scheduled_at(st["name"], st["account_name"])
            continue

        try:
            _schedule_range_execution(
                st["account_name"],
                st["name"],
                scheduled_at.astimezone(tz),
            )
            logger.info(
                "Scheduler: 已恢复预计执行任务 sign-%s-%s -> %s",
                st["account_name"],
                st["name"],
                scheduled_at.isoformat(),
            )
        except Exception as e:
            logger.error("Scheduler: 恢复预计执行任务失败: %s", e, exc_info=True)


async def _schedule_startup_range_catchups(sign_tasks: list[dict]) -> None:
    """启动时补跑逻辑 - 仅在没有有效预计执行时间时补建"""
    tz = _get_scheduler_timezone()
    logger = _get_scheduler_logger()
    now_utc = datetime.now(UTC)

    for st in sign_tasks:
        if not st.get("enabled", True) or st.get("execution_mode") != "range":
            continue

        existing_scheduled_at = _parse_scheduled_time(st.get("next_scheduled_at"))
        if existing_scheduled_at and existing_scheduled_at > now_utc:
            continue

        range_start = st.get("range_start")
        range_end = st.get("range_end")
        if not range_start or not range_end:
            continue

        now = datetime.now(tz)
        window = _parse_range_window(range_start, range_end, now)
        if window is None:
            logger.warning(
                f"Scheduler: 无法解析范围任务时间窗口 sign-{st['account_name']}-{st['name']} -> {range_start} - {range_end}"
            )
            continue

        start_dt, end_dt = window
        if now < start_dt or now > end_dt:
            continue

        if _has_run_on_local_day(st.get("last_run"), now, tz):
            logger.info(
                f"Scheduler: 跳过启动补跑 sign-{st['account_name']}-{st['name']}，今日已执行"
            )
            _clear_next_scheduled_at(st["name"], st["account_name"])
            continue

        remaining_seconds = max(0.0, (end_dt - now).total_seconds())
        if remaining_seconds <= 0:
            continue

        random_offset = random.uniform(0, remaining_seconds)
        actual_run_time = now + timedelta(seconds=random_offset)

        try:
            _schedule_range_execution(st["account_name"], st["name"], actual_run_time)
            logger.info(
                f"Scheduler: 已调度补跑任务 sign-{st['account_name']}-{st['name']} "
                f"到 {actual_run_time.strftime('%H:%M:%S')} (剩余窗口: {int(remaining_seconds)}秒)"
            )
        except Exception as e:
            logger.error(f"Scheduler: 调度补跑任务失败: {e}", exc_info=True)


def _log_scheduler_sync_summary(sign_tasks: list[dict]) -> None:
    if scheduler is None:
        return

    from backend.core.config import get_settings

    logger = _get_scheduler_logger()
    settings = get_settings()
    all_jobs = scheduler.get_jobs()
    logger.info(
        "Scheduler: 同步完成 timezone=%s sign_tasks=%s total_jobs=%s",
        settings.timezone,
        len(sign_tasks),
        len(all_jobs),
    )

    for st in sign_tasks:
        job_id = _cron_job_id(st['account_name'], st['name'])
        job = scheduler.get_job(job_id)
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else "None"
        if st.get("execution_mode") == "range" and st.get("range_start") and st.get("range_end"):
            schedule_desc = f"{st['range_start']} - {st['range_end']}"
        else:
            schedule_desc = st.get("sign_at", "")
        logger.info(
            "Scheduler: 已加载签到任务 id=%s mode=%s schedule=%s next_run=%s enabled=%s",
            job_id,
            st.get("execution_mode", "fixed"),
            schedule_desc,
            next_run,
            st.get("enabled", True),
        )


def get_scheduler_status(account_name: str | None = None) -> dict[str, object]:
    from backend.core.config import get_settings
    from backend.services.sign_tasks import get_sign_task_service

    settings = get_settings()
    jobs = scheduler.get_jobs() if scheduler else []
    sign_jobs = [job for job in jobs if job.id.startswith("sign-") and not job.id.startswith("sign-exec-")]

    sign_task_service = get_sign_task_service()
    sign_tasks = sign_task_service.list_tasks(force_refresh=True)
    if account_name:
        sign_tasks = [
            task for task in sign_tasks if task.get("account_name") == account_name
        ]
        sign_jobs = [
            job for job in sign_jobs if job.id.startswith(f"sign-{account_name}-")
        ]

    sign_task_statuses: list[dict[str, object]] = []
    for st in sign_tasks:
        job_id = _cron_job_id(st['account_name'], st['name'])
        job = scheduler.get_job(job_id) if scheduler else None
        execution_job = (
            scheduler.get_job(_range_execution_job_id(st["account_name"], st["name"]))
            if scheduler and st.get("execution_mode") == "range"
            else None
        )
        cron_next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        execution_next_run = (
            execution_job.next_run_time.isoformat()
            if execution_job and execution_job.next_run_time
            else None
        )

        sign_task_statuses.append(
            {
                "job_id": job_id,
                "account_name": st.get("account_name", ""),
                "task_name": st.get("name", ""),
                "enabled": bool(st.get("enabled", True)),
                "execution_mode": st.get("execution_mode", "fixed"),
                "schedule": (
                    f"{st.get('range_start')} - {st.get('range_end')}"
                    if st.get("execution_mode") == "range"
                    and st.get("range_start")
                    and st.get("range_end")
                    else st.get("sign_at", "")
                ),
                "next_run": cron_next_run,
                "next_scheduled_at": execution_next_run,
                "effective_next_run": execution_next_run or cron_next_run,
                "execution_job_exists": execution_job is not None,
                "job_exists": job is not None,
            }
        )

    return {
        "timezone": settings.timezone,
        "running": scheduler is not None,
        "total_jobs": len(jobs),
        "sign_job_count": len(sign_jobs),
        "sign_tasks": sign_task_statuses,
    }


async def _job_maintenance() -> None:
    """每日维护任务。"""
    return None


async def sync_jobs(schedule_range_catchup: bool = False) -> None:
    """
    Sync APScheduler jobs from sign tasks.
    """
    if scheduler is None:
        return

    from backend.services.sign_tasks import get_sign_task_service

    logger = _get_scheduler_logger()
    existing_ids = {
        job.id
        for job in scheduler.get_jobs()
        if job.id.startswith("sign-") and not job.id.startswith("sign-exec-")
    }
    desired_ids = set()

    sign_task_service = get_sign_task_service()
    sign_tasks = sign_task_service.list_tasks(force_refresh=True)
    for st in sign_tasks:
        job_id = _cron_job_id(st['account_name'], st['name'])
        desired_ids.add(job_id)

        if not st.get("enabled", True):
            if job_id in existing_ids:
                scheduler.remove_job(job_id)
            _clear_next_scheduled_at(st["name"], st["account_name"])
            continue

        try:
            trigger = create_cron_trigger(st["sign_at"])
            if st.get("execution_mode") == "range" and st.get("range_start"):
                trigger = create_cron_trigger(st["range_start"])

            if job_id in existing_ids:
                scheduler.reschedule_job(job_id, trigger=trigger)
            else:
                scheduler.add_job(
                    _job_run_sign_task,
                    trigger=trigger,
                    id=job_id,
                    args=[st["account_name"], st["name"]],
                    replace_existing=True,
                )
        except Exception as e:
            logger.error(
                f"Scheduler: 同步签到任务 {st['name']} 失败: {e}",
                exc_info=True,
            )

    for job_id in existing_ids - desired_ids:
        scheduler.remove_job(job_id)

    _log_scheduler_sync_summary(sign_tasks)
    if schedule_range_catchup:
        await _restore_pending_range_jobs(sign_tasks)
        await _schedule_startup_range_catchups(sign_tasks)


async def init_scheduler(sync_on_startup: bool = True) -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        from backend.core.config import get_settings

        settings = get_settings()
        logger = _get_scheduler_logger()
        scheduler = AsyncIOScheduler(
            timezone=settings.timezone,
            job_defaults={
                "misfire_grace_time": 3600,
                "coalesce": True,
                "max_instances": 10,
            },
        )
        scheduler.start()
        logger.info("Scheduler: 已启动 timezone=%s", settings.timezone)

        scheduler.add_job(
            _job_maintenance,
            trigger=CronTrigger.from_crontab("0 3 * * *"),
            id="system-maintenance",
            replace_existing=True,
        )

        if sync_on_startup:
            await sync_jobs(schedule_range_catchup=True)
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        scheduler = None


def add_or_update_sign_task_job(
    account_name: str, task_name: str, cron_expression: str, enabled: bool = True
) -> None:
    """动态添加或更新签到任务 Job"""
    global scheduler
    if not scheduler:
        return

    job_id = _cron_job_id(account_name, task_name)

    if not enabled:
        remove_sign_task_job(account_name, task_name)
        return

    try:
        trigger = create_cron_trigger(cron_expression)
        scheduler.add_job(
            _job_run_sign_task,
            trigger=trigger,
            id=job_id,
            args=[account_name, task_name],
            replace_existing=True,
        )
        print(f"Scheduler: 已添加/更新任务 {job_id} -> {cron_expression}")
    except Exception as e:
        print(f"Scheduler: 添加任务 {job_id} 失败: {e}")


def remove_sign_task_job(account_name: str, task_name: str) -> None:
    """动态移除签到任务 Job"""
    global scheduler
    if not scheduler:
        return

    cron_job_id = _cron_job_id(account_name, task_name)
    range_job_id = _range_execution_job_id(account_name, task_name)
    try:
        if scheduler.get_job(cron_job_id):
            scheduler.remove_job(cron_job_id)
            print(f"Scheduler: 已移除任务 {cron_job_id}")
        if scheduler.get_job(range_job_id):
            scheduler.remove_job(range_job_id)
        _clear_next_scheduled_at(task_name, account_name)
    except Exception as e:
        print(f"Scheduler: 移除任务 {cron_job_id} 失败: {e}")

