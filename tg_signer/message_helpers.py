from __future__ import annotations

from pyrogram.enums import ChatType
from pyrogram.types import Chat, InlineKeyboardMarkup, Message, ReplyKeyboardMarkup


def readable_message(message: Message) -> str:
    s = "\nMessage: "
    s += f"\n  text: {message.text or ''}"
    if message.photo:
        s += f"\n  图片: [({message.photo.width}x{message.photo.height}) {message.caption}]"
    if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
        s += "\n  InlineKeyboard: "
        for row in message.reply_markup.inline_keyboard:
            s += "\n   "
            for button in row:
                s += f"{button.text} | "
    return s


def readable_chat(chat: Chat) -> str:
    if chat.type == ChatType.BOT:
        type_ = "BOT"
    elif chat.type == ChatType.GROUP:
        type_ = "群组"
    elif chat.type == ChatType.SUPERGROUP:
        type_ = "超级群组"
    elif chat.type == ChatType.CHANNEL:
        type_ = "频道"
    else:
        type_ = "个人"

    none_or_dash = lambda x: x or "-"  # noqa: E731

    return f"id: {chat.id}, username: {none_or_dash(chat.username)}, title: {none_or_dash(chat.title)}, type: {type_}, name: {none_or_dash(chat.first_name)}"


def extract_keyboard_options(message: Message) -> list[str]:
    if not message.reply_markup:
        return []
    options = []
    if isinstance(message.reply_markup, ReplyKeyboardMarkup):
        for row in message.reply_markup.keyboard:
            for btn in row:
                btn_text = getattr(btn, "text", "")
                if btn_text:
                    options.append(btn_text)
    elif isinstance(message.reply_markup, InlineKeyboardMarkup):
        for row in message.reply_markup.inline_keyboard:
            for btn in row:
                btn_text = getattr(btn, "text", "")
                if btn_text:
                    options.append(btn_text)
    return options


def get_message_text_content(message: Message) -> str:
    return message.text or message.caption or ""


def poetry_message_signature(message: Message) -> tuple[str, tuple[str, ...]]:
    return (
        get_message_text_content(message),
        tuple(extract_keyboard_options(message)),
    )


def message_version(message: Message) -> tuple:
    reply_markup = message.reply_markup
    inline_buttons = ()
    reply_buttons = ()
    if isinstance(reply_markup, InlineKeyboardMarkup):
        inline_buttons = tuple(
            tuple(getattr(button, "text", "") for button in row)
            for row in reply_markup.inline_keyboard
        )
    elif isinstance(reply_markup, ReplyKeyboardMarkup):
        reply_buttons = tuple(
            tuple(getattr(button, "text", "") for button in row)
            for row in reply_markup.keyboard
        )
    return (
        message.id,
        message.text or "",
        message.caption or "",
        bool(message.photo),
        inline_buttons,
        reply_buttons,
        getattr(message, "edit_date", None),
        getattr(message, "date", None),
    )
