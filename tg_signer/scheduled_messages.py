from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta
from typing import Callable

from croniter import croniter


async def schedule_messages(
    *,
    app,
    user,
    login: Callable[..., object],
    log: Callable[..., None],
    print_to_user: Callable[[str], None],
    get_now: Callable[[], datetime],
    chat_id,
    text: str,
    crontab: str | None = None,
    next_times: int = 1,
    random_seconds: int = 0,
):
    now = get_now()
    it = croniter(crontab, start_time=now)
    if user is None:
        await login(print_chat=False)
    results = []
    async with app:
        for n in range(next_times):
            next_dt: datetime = it.next(ret_type=datetime) + timedelta(
                seconds=random.randint(0, random_seconds)
            )
            results.append({"at": next_dt.isoformat(), "text": text})
            await app.send_message(
                chat_id,
                text,
                schedule_date=next_dt,
            )
            await asyncio.sleep(0.1)
            print_to_user(f"已配置次数：{n + 1}")
    log(f"已配置定时发送消息，次数{next_times}")
    return results


async def get_scheduled_messages(
    *,
    app,
    user,
    login: Callable[..., object],
    print_to_user: Callable[[str], None],
    chat_id,
):
    if user is None:
        await login(print_chat=False)
    async with app:
        messages = await app.get_scheduled_messages(chat_id)
        for message in messages:
            print_to_user(f"{message.date}: {message.text}")
