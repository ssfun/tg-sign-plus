from backend.services.sign_task_run_summary import build_run_summary, sanitize_public_run_summary


def event(name, **meta):
    return {"event": name, "meta": meta}


def test_final_snapshot_wins_over_partial_retry_logs():
    summary = build_run_summary([
        event("event_engine_retry_started", retry_count=1),
        event("event_engine_final_state", status="checked", retry_count=3, current_response_index=2),
        event("task_completed", attempt=2, total_attempts=3),
    ], success=True)
    assert summary["status"] == "checked"
    assert summary["retry_count"] == 3
    assert summary["current_response_index"] == 2
    assert summary["attempt"] == 2


def test_cleanup_and_account_gates_stay_independent():
    summary = build_run_summary([
        event("account_lock_wait_started"),
        event("account_lock_acquired", wait_seconds=2),
        event("account_lock_released", success=True, attempt=1, total_attempts=1),
        event("global_concurrency_wait_timeout", timeout_seconds=10, wait_seconds=10),
        event("client_cleanup_failed", error_type="TimeoutError"),
        event("task_failed", error_type="TimeoutError", timeout_scope="outer_task"),
    ], success=False, error="task_name=private timed out")
    assert summary["account_lock"]["release_success"] is True
    assert summary["account_lock"]["wait_seconds"] == 2
    assert summary["global_concurrency"]["wait_timeout"] is True
    assert summary["global_concurrency"]["released"] is False
    assert summary["cleanup"]["failed"] is True
    assert summary["error_timeout_scope"] == "outer_task"
    assert "private" not in summary["error"]
    assert sanitize_public_run_summary(summary)["status"] == "failed"
