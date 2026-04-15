from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from pyrogram.types import InlineKeyboardMarkup, Message

from tg_signer.config import ClickKeyboardByTextAction, ChooseOptionByImageAction

from .message_helpers import (
    extract_keyboard_options,
    get_message_text_content,
    poetry_message_signature,
)

if TYPE_CHECKING:
    from .ai_tools import AITools


async def reply_by_calculation_problem(
    *,
    message: Message,
    log: Callable[..., None],
    send_message: Callable[..., Awaitable],
    get_ai_tools: Callable[[], "AITools"],
) -> bool:
    if not message.text:
        return False
    log(
        "检测到文本回复，尝试调用大模型进行计算题回答",
        stage="action",
        event="ai_calculation_started",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    log(
        f"问题: \n{message.text}",
        stage="message",
        event="ai_calculation_question",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    answer = await get_ai_tools().calculate_problem(message.text)
    answer = (answer or "").strip()
    log(
        f"回答为: {answer}",
        stage="action",
        event="ai_calculation_answer",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    if not answer:
        log(
            "AI 未返回有效答案",
            level="WARNING",
            stage="action",
            event="ai_calculation_empty_answer",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return False
    await send_message(message.chat.id, answer)
    return True


async def reply_by_image_recognition(
    *,
    message: Message,
    app,
    log: Callable[..., None],
    send_message: Callable[..., Awaitable],
    clean_text_for_send: Callable[[str], str],
    get_ai_tools: Callable[[], "AITools"],
) -> bool:
    if not message.photo:
        return False
    log(
        "检测到图片，尝试识别并发送文本",
        stage="action",
        event="ai_image_recognition_started",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    image_buffer = await app.download_media(message.photo.file_id, in_memory=True)
    image_buffer.seek(0)
    image_bytes = image_buffer.read()
    text = await get_ai_tools().extract_text_by_image(image_bytes)
    text = clean_text_for_send(text)
    if not text:
        log(
            "AI 未识别到可发送文本",
            level="WARNING",
            stage="action",
            event="ai_image_recognition_empty_result",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return False
    log(
        f"识别结果: {text}",
        stage="action",
        event="ai_image_recognition_result",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    await send_message(message.chat.id, text)
    return True


async def click_button_by_calculation_problem(
    *,
    message: Message,
    log: Callable[..., None],
    click_keyboard_by_text: Callable[..., Awaitable[bool]],
    get_ai_tools: Callable[[], "AITools"],
) -> bool:
    if not message.text:
        return False
    log(
        "检测到计算题，尝试计算并点击按钮",
        stage="action",
        event="ai_click_calculation_started",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    answer = await get_ai_tools().calculate_problem(message.text)
    answer = (answer or "").strip()
    if not answer:
        log(
            "AI 未返回可用于点击的答案",
            level="WARNING",
            stage="action",
            event="ai_click_calculation_empty_answer",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return False
    log(
        f"计算答案: {answer}",
        stage="action",
        event="ai_click_calculation_answer",
        meta={"chat_id": message.chat.id, "message_id": message.id},
    )
    proxy_action = ClickKeyboardByTextAction(text=answer)
    return await click_keyboard_by_text(proxy_action, message)


async def wait_for_poetry_followup_message(
    *,
    app,
    chat_messages: dict,
    chat_id: int,
    previous_message: Message,
    log: Callable[..., None],
    timeout: float = 5.0,
) -> Optional[Message]:
    previous_signature = poetry_message_signature(previous_message)
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        await asyncio.sleep(0.5)
        messages_dict = chat_messages.get(chat_id) or {}
        messages = [msg for msg in messages_dict.values() if msg is not None]
        for candidate in reversed(messages):
            if poetry_message_signature(candidate) != previous_signature:
                return candidate
    try:
        async for candidate in app.get_chat_history(chat_id, limit=5):
            if poetry_message_signature(candidate) != previous_signature:
                return candidate
    except Exception as e:
        log(
            f"查询填诗后续消息失败: {e}",
            level="WARNING",
            stage="message",
            event="ai_poetry_followup_query_failed",
            meta={"chat_id": chat_id, "error_type": type(e).__name__},
        )
    return None


async def click_button_by_poetry_fill(
    *,
    message: Message,
    app,
    chat_messages: dict,
    log: Callable[..., None],
    clean_text_for_send: Callable[[str], str],
    click_keyboard_by_text: Callable[..., Awaitable[bool]],
    get_ai_tools: Callable[[], "AITools"],
) -> bool:
    current_message = message
    clicked = False

    for round_idx in range(1, 7):
        message_text = get_message_text_content(current_message)
        if not message_text:
            break
        options = extract_keyboard_options(current_message)
        if not options:
            if not clicked:
                log(
                    "未找到可供填诗点击的按钮",
                    level="WARNING",
                    stage="action",
                    event="ai_poetry_no_buttons",
                    meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
                )
            break

        log(
            f"检测到填诗题，尝试第 {round_idx} 轮推断并点击按钮",
            stage="action",
            event="ai_poetry_round_started",
            meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
        )
        log(
            f"当前题面: {message_text}",
            stage="message",
            event="ai_poetry_prompt",
            meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
        )
        log(
            f"当前候选按钮: {options}",
            stage="action",
            event="ai_poetry_options",
            meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
        )
        answer = await get_ai_tools().solve_poetry_fill(message_text, options)
        answer = clean_text_for_send(answer)
        if not answer:
            log(
                "AI 未返回可用于填诗点击的答案",
                level="WARNING",
                stage="action",
                event="ai_poetry_empty_answer",
                meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
            )
            return clicked

        log(
            f"填诗答案: {answer}",
            stage="action",
            event="ai_poetry_answer",
            meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
        )
        candidates = [answer]
        if len(answer) > 1:
            candidates.extend([char for char in answer if char.strip()])

        deduped_candidates = []
        seen_candidates = set()
        for candidate in candidates:
            cleaned_candidate = clean_text_for_send(candidate)
            if not cleaned_candidate or cleaned_candidate in seen_candidates:
                continue
            seen_candidates.add(cleaned_candidate)
            deduped_candidates.append(cleaned_candidate)
        log(
            f"尝试匹配的填诗候选: {deduped_candidates}",
            stage="action",
            event="ai_poetry_candidates",
            meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
        )

        round_clicked = False
        for candidate in deduped_candidates:
            proxy_action = ClickKeyboardByTextAction(text=candidate)
            if await click_keyboard_by_text(proxy_action, current_message):
                round_clicked = True
                clicked = True
                break

        if not round_clicked:
            log(
                "填诗答案未匹配到任何按钮",
                level="WARNING",
                stage="action",
                event="ai_poetry_button_not_matched",
                meta={"chat_id": current_message.chat.id, "message_id": current_message.id, "round": round_idx},
            )
            return clicked

        followup_message = await wait_for_poetry_followup_message(
            app=app,
            chat_messages=chat_messages,
            chat_id=current_message.chat.id,
            previous_message=current_message,
            log=log,
            timeout=4.0,
        )
        if not followup_message:
            break
        current_message = followup_message

    return clicked


async def choose_option_by_image(
    *,
    message: Message,
    app,
    log: Callable[..., None],
    request_callback_answer: Callable[..., Awaitable[bool]],
    get_ai_tools: Callable[[], "AITools"],
) -> bool:
    if reply_markup := message.reply_markup:
        if isinstance(reply_markup, InlineKeyboardMarkup) and message.photo:
            flat_buttons = (b for row in reply_markup.inline_keyboard for b in row)
            option_to_btn = {btn.text: btn for btn in flat_buttons if btn.text}
            log(
                "检测到图片，尝试调用大模型进行图片识别并选择选项",
                stage="action",
                event="ai_choose_image_started",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            image_buffer = await app.download_media(message.photo.file_id, in_memory=True)
            image_buffer.seek(0)
            image_bytes = image_buffer.read()
            options = list(option_to_btn)
            if not options:
                log(
                    "未找到可供点击的按钮",
                    level="WARNING",
                    stage="action",
                    event="ai_choose_image_no_buttons",
                    meta={"chat_id": message.chat.id, "message_id": message.id},
                )
                return False
            result_index = await get_ai_tools().choose_option_by_image(
                image_bytes,
                "选择正确的选项",
                list(enumerate(options, start=1)),
            )
            log(
                f"AI 返回选项序号: {result_index}",
                stage="action",
                event="ai_choose_image_result_index",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            if not 1 <= result_index <= len(options):
                log(
                    f"AI 返回了非法选项序号: {result_index}，可选范围为 1 到 {len(options)}",
                    level="WARNING",
                    stage="action",
                    event="ai_choose_image_invalid_index",
                    meta={"chat_id": message.chat.id, "message_id": message.id, "result_index": result_index, "option_count": len(options)},
                )
                return False
            result = options[result_index - 1]
            log(
                f"选择结果为: {result}",
                stage="action",
                event="ai_choose_image_result",
                meta={"chat_id": message.chat.id, "message_id": message.id, "result": result},
            )
            target_btn = option_to_btn.get(result.strip())
            if not target_btn:
                log(
                    "未找到匹配的按钮",
                    level="WARNING",
                    stage="action",
                    event="ai_choose_image_target_not_found",
                    meta={"chat_id": message.chat.id, "message_id": message.id, "result": result},
                )
                return False
            return await request_callback_answer(
                app,
                message.chat.id,
                message.id,
                target_btn.callback_data,
            )
    return False
