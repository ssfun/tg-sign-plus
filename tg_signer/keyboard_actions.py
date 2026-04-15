from __future__ import annotations

from typing import Awaitable, Callable

from pyrogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from tg_signer.config import ClickKeyboardByTextAction


async def click_keyboard_by_text(
    *,
    action: ClickKeyboardByTextAction,
    message: Message,
    app,
    log: Callable[..., None],
    send_message: Callable[..., Awaitable],
    request_callback_answer: Callable[..., Awaitable[bool]],
    clean_text_for_match: Callable[[str], str],
) -> bool:
    target_text = clean_text_for_match(action.text)
    if not target_text:
        log(
            "Click button action has empty target text after cleaning",
            level="WARNING",
            stage="action",
            event="keyboard_target_empty",
            meta={"target_text": action.text},
        )
        return False

    if reply_markup := message.reply_markup:
        if isinstance(reply_markup, InlineKeyboardMarkup):
            flat_buttons = (b for row in reply_markup.inline_keyboard for b in row)
            for btn in flat_buttons:
                if not btn.text:
                    continue
                btn_text_clean = clean_text_for_match(btn.text)
                if target_text in btn_text_clean:
                    log(
                        f"成功匹配到并点击按钮: [{btn.text}] (匹配词: {action.text})",
                        stage="action",
                        event="inline_button_clicked",
                        meta={"button_text": btn.text, "target_text": action.text, "chat_id": message.chat.id, "message_id": message.id},
                    )
                    return await request_callback_answer(
                        app,
                        message.chat.id,
                        message.id,
                        btn.callback_data,
                    )
            log(
                f"Target button '{action.text}' not found in inline keyboard.",
                level="WARNING",
                stage="action",
                event="inline_button_not_found",
                meta={"target_text": action.text, "chat_id": message.chat.id, "message_id": message.id},
            )
        elif isinstance(reply_markup, ReplyKeyboardMarkup):
            for row in reply_markup.keyboard:
                for btn in row:
                    btn_text = getattr(btn, "text", "")
                    if not btn_text:
                        continue
                    btn_text_clean = clean_text_for_match(btn_text)
                    if target_text in btn_text_clean:
                        log(
                            f"成功匹配并发送回复键盘文本: [{btn_text}] (匹配词: {action.text})",
                            stage="action",
                            event="reply_keyboard_sent",
                            meta={"button_text": btn_text, "target_text": action.text, "chat_id": message.chat.id, "message_id": message.id},
                        )
                        await send_message(message.chat.id, btn_text)
                        return True
            log(
                f"Target button '{action.text}' not found in reply keyboard.",
                level="WARNING",
                stage="action",
                event="reply_keyboard_not_found",
                meta={"target_text": action.text, "chat_id": message.chat.id, "message_id": message.id},
            )
    return False
