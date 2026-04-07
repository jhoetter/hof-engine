"""Unit tests for web session phase + API extras."""

from hof.browser.web_session_view import build_web_session_view_extras, compute_web_session_phase


def test_phase_idle_is_succeeded() -> None:
    d = {"status": "idle", "messages": []}
    assert compute_web_session_phase(d) == "succeeded"
    ex = build_web_session_view_extras(d)
    assert ex["phase"] == "succeeded"
    assert ex["status_label"] == "Completed"


def test_phase_stopped_is_cancelled() -> None:
    d = {"status": "stopped", "messages": []}
    assert compute_web_session_phase(d) == "cancelled"


def test_phase_timed_out() -> None:
    d = {"status": "timed_out", "messages": []}
    assert compute_web_session_phase(d) == "timed_out"


def test_phase_error_and_poll_error() -> None:
    d = {"status": "error", "messages": [], "failure_code": "cloud_error", "failure_message": "x"}
    assert compute_web_session_phase(d) == "failed"
    ex = build_web_session_view_extras(d)
    assert ex["failure_code"] == "cloud_error"


def test_phase_running_with_login_hint() -> None:
    d = {
        "status": "running",
        "messages": [
            {
                "summary": "Need to complete login on this page",
                "role": "ai",
                "type": "browser_action",
            }
        ],
    }
    assert compute_web_session_phase(d) == "waiting_for_user"
    ex = build_web_session_view_extras(d)
    assert ex["phase"] == "waiting_for_user"
    assert ex["status_label"] == "Needs you"


def test_phase_running_plain() -> None:
    d = {
        "status": "running",
        "messages": [{"summary": "Clicking search box", "role": "ai", "type": "browser_action"}],
    }
    assert compute_web_session_phase(d) == "running"


def test_checkpoints_surface() -> None:
    d = {
        "status": "running",
        "messages": [],
        "checkpoints": ["Open page", "Click login"],
    }
    ex = build_web_session_view_extras(d)
    assert ex["checkpoint_count"] == 2
    assert ex["checkpoint_last"] == "Click login"
