from __future__ import annotations

from io import BytesIO

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tg_signer.ai_tools import _option_index_from_ai_response
from tg_signer.config import SignChatV3
from tg_signer.event_runner import SignEventRunner


class FakeChat:
    id = 1429576125


class FakePhoto:
    file_id = "captcha-image"
    file_unique_id = "captcha-image-unique"
    width = 240
    height = 160


class FakeMessage:
    id = 182007
    chat = FakeChat()
    text = None
    caption = "请在 30 秒内点击图中事物的按钮以完成签到"
    photo = FakePhoto()
    outgoing = False
    from_user = None
    date = None
    edit_date = None
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("丝袜", callback_data="stockings"),
                InlineKeyboardButton("灯", callback_data="lamp"),
                InlineKeyboardButton("电视盒子", callback_data="tv-box"),
                InlineKeyboardButton("键盘", callback_data="keyboard"),
            ]
        ]
    )


class FakeApp:
    async def download_media(self, _file_id: str, *, in_memory: bool = True):
        return BytesIO(b"fake-image")


class FakeTools:
    async def choose_option_by_image(self, *_args, **_kwargs):
        return None


def make_runner(logs: list[dict]) -> SignEventRunner:
    chat = SignChatV3.parse_obj(
        {
            "chat_id": 1429576125,
            "actions": [
                {"action": 1, "text": "/checkin"},
                {"action": 4},
                {"action": 9, "keywords": ["签到成功", "签到过了"]},
            ],
        }
    )

    def log(message, *_, **kwargs):
        logs.append({"message": str(message), **kwargs})

    return SignEventRunner(
        chat=chat,
        app=FakeApp(),
        log=log,
        send_message=None,
        send_dice=None,
        request_callback_answer=None,
        get_ai_tools=lambda: FakeTools(),
    )


def test_option_index_from_ai_response_rejects_empty_or_bad_payloads():
    assert _option_index_from_ai_response(None) is None
    assert _option_index_from_ai_response([]) is None
    assert _option_index_from_ai_response({}) is None
    assert _option_index_from_ai_response({"option": None}) is None
    assert _option_index_from_ai_response({"option": True}) is None
    assert _option_index_from_ai_response({"option": "abc"}) is None


def test_option_index_from_ai_response_accepts_numeric_payloads():
    assert _option_index_from_ai_response({"option": 2}) == 2
    assert _option_index_from_ai_response({"option": "3"}) == 3
    assert _option_index_from_ai_response("4") == 4


def test_option_index_from_ai_response_accepts_button_text_payloads():
    options = [(1, "丝袜"), (2, "灯"), (3, "电视盒子"), (4, "键盘")]

    assert _option_index_from_ai_response({"answer": "灯"}, options) == 2
    assert _option_index_from_ai_response({"value": "电视盒子"}, options) == 3
    assert _option_index_from_ai_response("键盘", options) == 4


@pytest.mark.asyncio
async def test_image_option_empty_ai_result_is_unhandled_not_exception():
    logs: list[dict] = []
    runner = make_runner(logs)

    assert not await runner._choose_option_by_image(FakeMessage())
    assert any(item.get("event") == "event_engine_invalid_option_index" for item in logs)
