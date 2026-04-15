from __future__ import annotations

import asyncio
from typing import Union

from pyrogram import errors


async def request_callback_answer(
    *,
    client,
    chat_id: Union[int, str],
    message_id: int,
    callback_data: Union[str, bytes],
    log,
    callback_text_store=None,
    **kwargs,
) -> bool:
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = await client.request_callback_answer(
                chat_id, message_id, callback_data=callback_data, **kwargs
            )
            callback_text = getattr(result, "message", None) or getattr(result, "alert", None) or ""
            if isinstance(callback_text_store, dict):
                callback_text_store[chat_id] = str(callback_text or "")
            if callback_text:
                log(
                    f"点击完成，弹窗提示: {callback_text}",
                    stage="result",
                    event="callback_answer_received",
                    meta={"chat_id": chat_id, "message_id": message_id},
                )
            else:
                log("点击完成")
            return True
        except errors.FloodWait as e:
            wait_seconds = max(int(getattr(e, "value", 1) or 1), 1)
            log(
                f"触发 FloodWait，{wait_seconds}s 后重试 ({attempt}/{max_retries})",
                level="WARNING",
            )
            if attempt >= max_retries:
                log(e, level="ERROR")
                return False
            await asyncio.sleep(wait_seconds)
        except TimeoutError:
            log(
                "回调请求超时，按已触发点击处理，后续依赖消息更新继续推进",
                level="WARNING",
            )
            return True
        except errors.BadRequest as e:
            err_text = str(e).upper()
            if "DATA_INVALID" in err_text:
                log(
                    "按钮回调数据已失效，改为等待消息更新或历史消息继续执行",
                    level="WARNING",
                )
                return False
            log(e, level="ERROR")
            return False
    return False
