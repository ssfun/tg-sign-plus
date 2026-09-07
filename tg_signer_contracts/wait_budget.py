"""Explicit action-wait allowance shared by the worker and event engine."""

from collections.abc import Iterable, Mapping
from typing import Any


def action_wait_budget(actions: Iterable[Mapping[str, Any]], inline_retries: int) -> int:
    seconds = sum(
        action["seconds"]
        for action in actions
        if isinstance(action, Mapping)
        and action.get("action") == 10
        and type(action.get("seconds")) is int
        and 1 <= action["seconds"] <= 300
    )
    return seconds * (max(0, inline_retries) + 1)
