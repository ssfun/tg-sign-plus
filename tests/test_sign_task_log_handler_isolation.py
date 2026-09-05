from __future__ import annotations

import logging

from backend.services.sign_task_log_context import reset_sign_task_run_id, set_sign_task_run_id
from backend.services.sign_task_log_handler import TaskLogHandler
from backend.services.task_flow_logger import TaskFlowLogger


def test_task_log_handler_filters_by_current_run_context():
    logs_a: list[str] = []
    logs_b: list[str] = []
    items_a: list[dict] = []
    items_b: list[dict] = []
    offset_a = {"value": 0}
    offset_b = {"value": 0}
    handler_a = TaskLogHandler(logs_a, items_a, offset_a, run_id="run-a")
    handler_b = TaskLogHandler(logs_b, items_b, offset_b, run_id="run-b")

    logger = logging.getLogger("test.task_log_handler_isolation")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler_a)
    logger.addHandler(handler_b)

    token = set_sign_task_run_id("run-a")
    try:
        logger.info("message for a")
    finally:
        reset_sign_task_run_id(token)

    token = set_sign_task_run_id("run-b")
    try:
        logger.info("message for b")
    finally:
        reset_sign_task_run_id(token)

    logger.info("message without run")

    assert [item["text"] for item in items_a] == ["message for a"]
    assert [item["text"] for item in items_b] == ["message for b"]


def test_task_log_handler_prefers_record_run_id():
    logs: list[str] = []
    items: list[dict] = []
    handler = TaskLogHandler(logs, items, {"value": 0}, run_id="run-a")

    logger = logging.getLogger("test.task_log_handler_record_run_id")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    token = set_sign_task_run_id("run-b")
    try:
        logger.info("accepted", extra={"flow_run_id": "run-a"})
        logger.info("rejected", extra={"flow_run_id": "run-b"})
    finally:
        reset_sign_task_run_id(token)

    assert [item["text"] for item in items] == ["accepted"]


def test_task_flow_logger_can_keep_structured_item_without_text_log():
    logs: list[str] = []
    items: list[dict] = []
    logger = TaskFlowLogger(logs, items, {"value": 0})

    logger.append("visible message", event="visible")
    logger.append("diagnostic message", event="diagnostic", visible=False)

    assert [item["event"] for item in items] == ["visible", "diagnostic"]
    assert items[0]["text_visible"] is True
    assert items[1]["text_visible"] is False
    assert len(logs) == 1
    assert "visible message" in logs[0]


def test_task_log_handler_hides_text_when_record_marks_flow_invisible():
    logs: list[str] = []
    items: list[dict] = []
    handler = TaskLogHandler(logs, items, {"value": 0})

    logger = logging.getLogger("test.task_log_handler_visibility")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    logger.info("hidden diagnostic", extra={"flow_event": "diagnostic", "flow_visible": False})

    assert [item["text"] for item in items] == ["hidden diagnostic"]
    assert items[0]["text_visible"] is False
    assert logs == []
