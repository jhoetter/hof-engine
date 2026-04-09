"""Regression: runtime merge must not clobber terminal status with stale poll."""

import pytest

from hof.browser.store import merge_web_session_runtime_fields


def test_merge_does_not_clobber_terminal_stopped_with_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_saved: dict = {}

    monkeypatch.setattr(
        "hof.browser.store.load_web_session",
        lambda _sid: {"session_id": "s", "status": "stopped", "messages": []},
    )

    def capture_save(sid: str, payload: dict) -> None:
        last_saved.clear()
        last_saved.update(payload)

    monkeypatch.setattr("hof.browser.store.save_web_session", capture_save)
    merge_web_session_runtime_fields("s", cloud_status="running")
    assert last_saved.get("status") == "stopped"


def test_merge_updates_running_to_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    last_saved: dict = {}

    monkeypatch.setattr(
        "hof.browser.store.load_web_session",
        lambda _sid: {"session_id": "s", "status": "running", "messages": []},
    )

    def capture_save(_sid: str, payload: dict) -> None:
        last_saved.clear()
        last_saved.update(payload)

    monkeypatch.setattr("hof.browser.store.save_web_session", capture_save)
    merge_web_session_runtime_fields("s", cloud_status="idle")
    assert last_saved.get("status") == "idle"


def test_merge_skips_stale_non_terminal_when_step_regresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_saved: dict = {}

    monkeypatch.setattr(
        "hof.browser.store.load_web_session",
        lambda _sid: {
            "session_id": "s",
            "status": "running",
            "cloud_step_count": 10,
            "messages": [],
        },
    )

    def capture_save(_sid: str, payload: dict) -> None:
        last_saved.clear()
        last_saved.update(payload)

    monkeypatch.setattr("hof.browser.store.save_web_session", capture_save)
    merge_web_session_runtime_fields(
        "s",
        cloud_status="running",
        cloud_step_count=5,
    )
    assert last_saved.get("status") == "running"
    assert last_saved.get("cloud_step_count") == 10


def test_merge_terminal_status_applies_despite_step_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    last_saved: dict = {}

    monkeypatch.setattr(
        "hof.browser.store.load_web_session",
        lambda _sid: {
            "session_id": "s",
            "status": "running",
            "cloud_step_count": 10,
            "messages": [],
        },
    )

    def capture_save(_sid: str, payload: dict) -> None:
        last_saved.clear()
        last_saved.update(payload)

    monkeypatch.setattr("hof.browser.store.save_web_session", capture_save)
    merge_web_session_runtime_fields(
        "s",
        cloud_status="idle",
        cloud_step_count=5,
    )
    assert last_saved.get("status") == "idle"
    assert last_saved.get("cloud_step_count") == 10
