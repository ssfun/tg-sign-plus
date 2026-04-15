from __future__ import annotations

import asyncio
from typing import Callable

from pyrogram.types import Message

from .message_helpers import readable_message


async def store_incoming_message(
    *,
    message: Message,
    context,
    log: Callable[..., None],
) -> None:
    chats = context.sign_chats.get(message.chat.id)
    if not chats:
        log(
            "忽略意料之外的聊天",
            level="WARNING",
            stage="message",
            event="unexpected_chat_ignored",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return
    context.chat_messages[message.chat.id][message.id] = message


async def handle_incoming_message(
    *,
    client,
    message: Message,
    context,
    log: Callable[..., None],
) -> None:
    from_user = message.from_user
    sender = (from_user.username or from_user.id) if from_user else "unknown"
    log(
        f"收到来自「{sender}」的消息: {readable_message(message)}",
        stage="message",
        event="incoming_message",
        meta={"chat_id": message.chat.id, "message_id": message.id, "sender": str(sender)},
    )
    await store_incoming_message(message=message, context=context, log=log)


async def handle_edited_message(
    *,
    client,
    message: Message,
    context,
    log: Callable[..., None],
) -> None:
    from_user = message.from_user
    sender = (from_user.username or from_user.id) if from_user else "unknown"
    log(
        f"收到来自「{sender}」对消息的更新，消息: {readable_message(message)}",
        stage="message",
        event="edited_message",
        meta={"chat_id": message.chat.id, "message_id": message.id, "sender": str(sender)},
    )
    while context.waiting_message and context.waiting_message.id == message.id:
        await asyncio.sleep(0.3)
    await store_incoming_message(message=message, context=context, log=log)
