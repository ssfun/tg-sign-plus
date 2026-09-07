import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.api.routes.sign_tasks import ChatConfig
from tg_signer.config import SignChatV3, WaitAction
from tg_signer.event_runner import EventRunStatus, SignEventRunner, build_event_spec


SEND = {"action": 1, "text": "/sign"}
WAIT = {"action": 10, "seconds": 1}
CLICK = {"action": 3, "text": "签到"}


def make_runner(actions, **options):
    chat = SignChatV3.parse_obj({"chat_id": 123, "actions": actions, "event_history_limit": 0, **options})
    events = []
    started = asyncio.Event()

    def log(*args, **kwargs):
        events.append(kwargs.get("event"))
        if kwargs.get("event") == "event_engine_wait_started":
            started.set()

    sends = []

    async def send(*args):
        sends.append(asyncio.get_running_loop().time())
        return SimpleNamespace(id=len(sends), date=None)

    runner = SignEventRunner(chat=chat, app=None, log=log, send_message=send,
                             send_dice=send, request_callback_answer=None, get_ai_tools=None)
    return runner, sends, events, started


@pytest.mark.parametrize("seconds", [None, True, False, 0, -1, 301, 1.5, "5", float("inf"), float("nan")])
def test_wait_validation_matches_api_and_worker(seconds):
    for model in (ChatConfig, SignChatV3):
        with pytest.raises(ValidationError):
            model.parse_obj({"chat_id": 123, "actions": [{"action": 10, "seconds": seconds}]})


@pytest.mark.parametrize("seconds", [1, 5, 300])
def test_wait_roundtrip(seconds):
    payload = {"chat_id": 123, "actions": [SEND, {"action": 10, "seconds": seconds}, SEND]}
    api = ChatConfig.parse_obj(payload)
    worker = SignChatV3.parse_raw(api.json())
    assert worker.dict()["actions"] == payload["actions"]
    assert isinstance(worker.actions[1], WaitAction)


def test_spec_preserves_waits_on_both_sides_of_response_action():
    actions = [WAIT, SEND, WAIT, CLICK, WAIT, SEND, WAIT]
    spec = build_event_spec(SignChatV3.parse_obj({"chat_id": 123, "actions": actions}))
    assert [a.dict() for a in spec.send_actions] == actions[:3]
    assert [a.dict() for a in spec.response_actions] == actions[3:]


@pytest.mark.asyncio
async def test_repeated_sends_wait_without_inbound_messages():
    runner, sends, events, _ = make_runner([SEND, WAIT, SEND, WAIT, SEND])
    result = await asyncio.wait_for(runner.run(), 4)
    assert result.status == EventRunStatus.SUCCESS
    assert len(sends) == 3
    assert all(b - a >= 0.95 for a, b in zip(sends, sends[1:]))
    assert events.count("event_engine_wait_completed") == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("after_click", [False, True])
async def test_cancel_during_wait_prevents_next_send(after_click):
    runner, sends, _, started = make_runner([SEND, CLICK, WAIT, SEND] if after_click else [SEND, WAIT, SEND])
    if after_click:
        runner.current_response_index = 1
        task = asyncio.create_task(runner._drain_immediate_response_actions())
    else:
        task = asyncio.create_task(runner.run())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(sends) == (0 if after_click else 1)


@pytest.mark.asyncio
async def test_finish_interrupts_wait_without_sending_followup():
    runner, sends, _, started = make_runner([SEND, WAIT, SEND])
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(started.wait(), 1)
    runner._finish(EventRunStatus.FAILED, "stopped")
    assert (await asyncio.wait_for(task, 0.3)).status == EventRunStatus.FAILED
    assert len(sends) == 1


@pytest.mark.asyncio
async def test_click_then_wait_is_not_limited_by_response_rpc_timeout():
    runner, sends, _, _ = make_runner([SEND, CLICK, WAIT, SEND])
    runner.action_timeout = 0.05
    runner._execute_response_action = AsyncMock(return_value=True)
    assert await asyncio.wait_for(runner._handle_current_response_action(SimpleNamespace(id=1)), 2)
    assert len(sends) == 1
    assert runner.current_response_index == 3
    assert runner.result.status == EventRunStatus.SUCCESS


@pytest.mark.asyncio
async def test_inbound_callback_cannot_advance_while_initial_wait_runs():
    runner, sends, _, started = make_runner([SEND, WAIT, SEND, CLICK])
    runner._handle_message_locked = AsyncMock()
    runner._is_inbound_chat_message = lambda _: True
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(started.wait(), 1)
    message_task = asyncio.create_task(runner.handle_message(inbound_message("ordinary message")))
    await asyncio.sleep(0)
    assert not message_task.done()
    assert len(sends) == 1
    await asyncio.wait_for(message_task, 2)
    assert len(sends) == 2
    runner._finish(EventRunStatus.SUCCESS)
    await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_inline_retry_replays_wait_between_entry_sends():
    runner, sends, events, _ = make_runner([SEND, WAIT, SEND, CLICK], event_retry_wait=0)
    runner._schedule_retry("test")
    await asyncio.wait_for(runner._retry_task, 2)
    assert len(sends) == 2
    assert sends[1] - sends[0] >= 0.95
    assert events.count("event_engine_wait_completed") == 1
    assert runner.current_response_index == 0


@pytest.mark.asyncio
async def test_event_timeout_reserves_configured_wait_budget():
    runner, sends, _, started = make_runner([SEND, CLICK, WAIT, SEND], event_retries=0)
    runner.timeout = 0.1
    runner._execute_response_action = AsyncMock(return_value=True)
    run_task = asyncio.create_task(runner.run())
    # Initial sending yields to the event loop; wait until the runner reaches its response phase.
    while not sends:
        await asyncio.sleep(0)
    async with runner.message_lock:
        response_task = asyncio.create_task(runner._handle_current_response_action(SimpleNamespace(id=1)))
        await asyncio.wait_for(started.wait(), 1)
        assert await asyncio.wait_for(response_task, 2)
    assert (await asyncio.wait_for(run_task, 1)).status == EventRunStatus.SUCCESS
    assert len(sends) == 2


def inbound_message(text, **overrides):
    return SimpleNamespace(**{
        "id": 20, "chat": SimpleNamespace(id=123), "text": text,
        "caption": None, "photo": None, "reply_markup": None,
        "outgoing": False, "from_user": None, "date": None, "edit_date": None,
        **overrides,
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["entry", "response", "retry"])
async def test_success_message_interrupts_wait_without_followup(phase):
    actions = [SEND, CLICK, WAIT, SEND] if phase == "response" else [SEND, WAIT, SEND]
    runner, sends, _, started = make_runner(actions + [{"action": 9, "keywords": ["签到成功"]}], event_retry_wait=0)
    response_task = None
    if phase == "retry":
        runner._schedule_retry("test")
        task = runner._retry_task
    else:
        task = asyncio.create_task(runner.run())
        if phase == "response":
            runner._execute_response_action = AsyncMock(return_value=True)
            while not sends:
                await asyncio.sleep(0)
            response_task = asyncio.create_task(runner.handle_message(inbound_message("点击签到")))
    try:
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.wait_for(runner.handle_message(inbound_message("签到成功", id=21)), 0.3)
        await asyncio.wait_for(task, 0.5)
        if response_task:
            await asyncio.wait_for(response_task, 0.3)
        assert runner.result.status == EventRunStatus.SUCCESS
        assert len(sends) == 1
        assert runner._completed_wait_seconds == 0
        if phase == "response":
            runner._execute_response_action.assert_awaited_once()
    finally:
        for pending in (task, response_task):
            if pending and not pending.done():
                pending.cancel()
        await asyncio.gather(*(pending for pending in (task, response_task) if pending), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["outgoing", "other_chat", "stale", "duplicate"])
async def test_wait_result_fast_path_preserves_message_filters(kind):
    from tg_signer.message_helpers import message_version

    runner, sends, _, started = make_runner([SEND, WAIT, SEND, {"action": 9, "keywords": ["成功"]}])
    message = inbound_message("成功")
    if kind == "outgoing":
        message.outgoing = True
    elif kind == "other_chat":
        message.chat = SimpleNamespace(id=456)
    elif kind == "stale":
        runner.stale_attempt_versions.add(message_version(message))
    else:
        runner.processed_versions.add(message_version(message))
    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(started.wait(), 1)
    ignored = asyncio.create_task(runner.handle_message(message))
    await asyncio.sleep(0)
    assert not runner.finished.is_set()
    await asyncio.wait_for(runner.handle_message(inbound_message("成功", id=21)), 0.3)
    await asyncio.wait_for(asyncio.gather(task, ignored), 0.5)
    assert len(sends) == 1


@pytest.fixture
def default_budget_env(monkeypatch):
    for key in ("SIGN_TASK_RUN_TIMEOUT", "SIGN_TASK_RUN_TIMEOUT_OVERHEAD", "TG_EVENT_ENGINE_TIMEOUT", "TG_EVENT_ENGINE_INLINE_RETRIES"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_worker_reserves_all_waits_across_chats_and_retries(default_budget_env):
    from backend.services.sign_task_executor import SignTaskExecutor

    config = {"sign_interval": 5, "chats": [
        {"chat_id": 123, "actions": [SEND, {"action": 10, "seconds": 300}, SEND]},
        {"chat_id": 456, "event_timeout": 60, "event_retries": 0, "actions": [WAIT, WAIT]},
    ]}
    # 120 + 300 * 4, then 60 + 2 * 1, plus inter-chat delay and worker overhead.
    assert SignTaskExecutor.task_timeout_seconds(config) == 1477


def test_worker_uses_retry_environment_but_preserves_explicit_zero(default_budget_env):
    from backend.services.sign_task_executor import SignTaskExecutor

    default_budget_env.setenv("TG_EVENT_ENGINE_INLINE_RETRIES", "2")
    chat = {"chat_id": 123, "actions": [{"action": 10, "seconds": 300}]}
    assert SignTaskExecutor.task_timeout_seconds({"chats": [chat]}) == 1110
    chat["event_retries"] = 0
    assert SignTaskExecutor.task_timeout_seconds({"chats": [chat]}) == 510
    chat["actions"] = [SEND]
    assert SignTaskExecutor.task_timeout_seconds({"chats": [chat]}) == 210


@pytest.mark.asyncio
async def test_entry_wait_is_not_counted_again_in_event_timer(monkeypatch):
    from tg_signer.event_runner import EventRunResult

    runner, _, _, _ = make_runner([SEND, WAIT, {"action": 9, "keywords": ["成功"]}], event_retries=0)
    runner.timeout = 0.1
    runner._wait_finished = AsyncMock(return_value=EventRunResult(EventRunStatus.SUCCESS))
    original_wait_for = asyncio.wait_for
    timeouts = []

    async def record_wait_for(awaitable, timeout):
        timeouts.append(timeout)
        return await original_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", record_wait_for)
    await runner.run()
    assert timeouts == [1, 0.1]
    assert runner._completed_wait_seconds == 1


@pytest.mark.asyncio
async def test_success_arriving_before_wait_starts_is_not_queued():
    runner, sends, events, _ = make_runner([SEND, WAIT, SEND, {"action": 9, "keywords": ["成功"]}])
    send_started = asyncio.Event()
    release_send = asyncio.Event()
    original_send = runner.send_message

    async def slow_send(*args):
        message = await original_send(*args)
        send_started.set()
        await release_send.wait()
        return message

    runner.send_message = slow_send
    task = asyncio.create_task(runner.run())
    try:
        await asyncio.wait_for(send_started.wait(), 1)
        await asyncio.wait_for(runner.handle_message(inbound_message("成功")), 0.3)
        assert runner.finished.is_set()
        release_send.set()
        assert (await asyncio.wait_for(task, 0.5)).status == EventRunStatus.SUCCESS
        assert len(sends) == 1
        assert "event_engine_wait_started" not in events
    finally:
        release_send.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
