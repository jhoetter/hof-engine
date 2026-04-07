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
