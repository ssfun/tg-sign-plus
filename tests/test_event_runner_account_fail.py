from __future__ import annotations

from tg_signer.config import SignChatV3
from tg_signer.event_runner import SignEventRunner


def make_runner(actions: list[dict]) -> SignEventRunner:
    chat = SignChatV3.parse_obj({"chat_id": 8321810754, "actions": actions})
    return SignEventRunner(
        chat=chat,
        app=None,
        log=lambda *args, **kwargs: None,
        send_message=None,
        send_dice=None,
        request_callback_answer=None,
        get_ai_tools=lambda: None,
    )


def test_unregistered_text_is_not_a_default_hard_failure():
    runner = make_runner(
        [
            {"action": 1, "text": "/start"},
            {"action": 3, "text": "签到"},
            {"action": 9, "keywords": ["签到成功", "签到过了"]},
        ]
    )

    assert not runner._classify_text("账号未注册也可以继续签到")
    assert not runner.finished.is_set()


def test_legacy_account_fail_keywords_are_ignored_by_event_runner():
    runner = make_runner(
        [
            {"action": 1, "text": "/start"},
            {"action": 3, "text": "签到"},
            {
                "action": 9,
                "keywords": ["签到成功", "签到过了"],
                "account_fail_keywords": ["未注册"],
            },
        ]
    )

    assert not runner._classify_text("账号未注册，请先注册")
    assert not runner.finished.is_set()


def test_generic_success_words_are_not_default_result_keywords():
    runner = make_runner(
        [
            {"action": 1, "text": "/start"},
            {"action": 3, "text": "签到"},
            {"action": 9, "keywords": ["签到成功"]},
        ]
    )

    assert not runner._classify_text("操作成功")
    assert not runner.finished.is_set()
