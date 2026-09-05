from __future__ import annotations

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tg_signer.config import SignChatV3
from tg_signer.event_runner import SignEventRunner


class FakeChat:
    id = 8476074387


class FakeMessage:
    def __init__(self, text: str, *, message_id: int = 180075):
        self.id = message_id
        self.chat = FakeChat()
        self.text = None
        self.caption = text
        self.photo = None
        self.outgoing = False
        self.from_user = None
        self.date = None
        self.edit_date = None
        self.reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("轩", callback_data="xuan"),
                    InlineKeyboardButton("行", callback_data="xing"),
                ]
            ]
        )


class FakeTools:
    def __init__(self, answers: list[str]):
        self.answers = answers

    async def solve_poetry_fill(self, _text: str, _options: list[str]) -> str:
        return self.answers.pop(0)


def make_runner(answers: list[str]) -> SignEventRunner:
    chat = SignChatV3.parse_obj(
        {
            "chat_id": 8476074387,
            "actions": [
                {"action": 1, "text": "/start"},
                {"action": 3, "text": "签到"},
                {"action": 8},
                {"action": 9, "keywords": ["签到成功", "签到过了"]},
            ],
        }
    )
    runner = SignEventRunner(
        chat=chat,
        app=None,
        log=lambda *args, **kwargs: None,
        send_message=None,
        send_dice=None,
        request_callback_answer=None,
        get_ai_tools=lambda: FakeTools(answers),
    )
    runner.current_response_index = 1
    runner._click_button = _always_click  # type: ignore[method-assign]
    return runner


async def _always_click(_message, _target_text: str, *, trusted_timeout: bool = True) -> bool:
    return True


@pytest.mark.asyncio
async def test_poetry_action_stays_current_while_multiple_blanks_remain():
    runner = make_runner(["轩", "行"])

    first_round = FakeMessage("夜来幽梦忽还乡。小░窗。正梳妆。相顾无言，惟有泪千░。")
    assert await runner._handle_current_response_action(first_round)
    assert runner.current_response_index == 1

    second_round = FakeMessage("夜来幽梦忽还乡。小轩窗。正梳妆。相顾无言，惟有泪千░。")
    assert await runner._handle_current_response_action(second_round)
    assert runner.current_response_index == 2


@pytest.mark.asyncio
async def test_poetry_action_advances_when_only_one_blank_remains():
    runner = make_runner(["行"])

    message = FakeMessage("夜来幽梦忽还乡。小轩窗。正梳妆。相顾无言，惟有泪千░。")
    assert await runner._handle_current_response_action(message)
    assert runner.current_response_index == 2
