"""Tests for hof.agent (policy, attachment defaults, stream fold)."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import patch

import pytest

from llm_markdown.agent_stream import (
    AgentContentDelta,
    AgentMessageFinish,
    AgentToolCallDelta,
)

from hof.agent.policy import (
    BUILTIN_AGENT_TOOL_NAMES,
    AgentPolicy,
    InboxWatchDescriptor,
    MutationBatchEntry,
    MutationPreviewResult,
    PostApplyReviewHint,
    configure_agent,
    get_agent_policy,
    inbox_watch_to_wire,
)
from hof.agent.state import load_agent_run, save_agent_run
from hof.agent.stream import (
    _agent_stream_error_event,
    _AgentStreamTurnExhaustedError,
    _append_client_messages,
    _iter_stream_agent_turn_with_engine_retries,
    _mutation_preview_payload,
    collect_agent_chat_from_stream,
    default_normalize_attachments,
    iter_agent_chat_stream,
    iter_agent_resume_inbox_stream,
    iter_agent_resume_stream,
)


def test_default_normalize_attachments_accepts_keys() -> None:
    raw = [{"object_key": "tenant/x.pdf", "filename": "x.pdf"}]
    out, err = default_normalize_attachments(raw)
    assert err is None
    assert out == [{"object_key": "tenant/x.pdf", "filename": "x.pdf"}]


def test_default_normalize_attachments_rejects_non_list() -> None:
    out, err = default_normalize_attachments("nope")
    assert out == []
    assert err == "attachments must be a list"


def test_append_client_messages_empty_last_user_with_attachments() -> None:
    oa: list[dict] = [{"role": "system", "content": "sys"}]
    _append_client_messages(
        oa,
        [{"role": "user", "content": ""}],
        [{"object_key": "tenant/x.pdf"}],
    )
    assert len(oa) == 2
    assert oa[1] == {"role": "user", "content": "\u2060"}


def test_append_client_messages_empty_last_user_no_attachments_skipped() -> None:
    oa: list[dict] = [{"role": "system", "content": "sys"}]
    _append_client_messages(oa, [{"role": "user", "content": "   "}], [])
    assert len(oa) == 1


def test_append_client_messages_strips_user_and_assistant() -> None:
    oa: list[dict] = [{"role": "system", "content": "sys"}]
    _append_client_messages(
        oa,
        [
            {"role": "user", "content": "  hi  "},
            {"role": "assistant", "content": "  ok  "},
        ],
        [],
    )
    assert oa[1:] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]


def test_collect_agent_chat_from_stream_tool_result_pending_confirmation() -> None:
    def events():
        yield {"type": "tool_result", "name": "x", "summary": "s", "pending_confirmation": True}

    out = collect_agent_chat_from_stream(events())
    evs = out.get("events") or []
    assert len(evs) == 1
    assert evs[0].get("pending_confirmation") is True


def test_agent_policy_confirmation_summary_mode_default() -> None:
    p = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset(),
        system_prompt_intro="x",
    )
    assert p.confirmation_summary_mode == "llm_stream"


def test_mutation_preview_payload() -> None:
    policy = AgentPolicy(
        allowlist_read=frozenset(),
        allowlist_mutation=frozenset({"m1", "m2"}),
        system_prompt_intro="x",
        mutation_preview={
            "m1": lambda a: {"ok": True, "n": a.get("x")},
            "m2": lambda _a: MutationPreviewResult(
                summary="Line",
                data={"k": 1},
            ),
        },
    )
    assert _mutation_preview_payload("m1", '{"x": 3}', policy) == {
        "summary": '{"n": 3, "ok": true}',
        "data": {"ok": True, "n": 3},
    }
    assert _mutation_preview_payload("m2", "{}", policy) == {
        "summary": "Line",
        "data": {"k": 1},
    }
    assert _mutation_preview_payload("m1", "not json", policy) is None
    assert _mutation_preview_payload("other", "{}", policy) is None


def test_resume_emits_mutation_applied_from_post_apply_hook(monkeypatch) -> None:
    """After confirm, engine yields mutation_applied when policy hook returns a hint."""

    from hof.functions import function

    @function
    def mut_review() -> dict:
        """Mutation that ends in manager review."""
        return {"approval_status": "pending_review", "ok": True}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def hook(
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> PostApplyReviewHint | None:
        if result.get("approval_status") == "pending_review":
            return PostApplyReviewHint(
                label="Manager review",
                path="/inbox",
                url="http://localhost/inbox",
            )
        return None

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_review"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            mutation_post_apply={"mut_review": hook},
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_r",
            name="mut_review",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    ac = [e for e in ev1 if e.get("type") == "awaiting_confirmation"]
    assert len(ac) == 1
    pids = ac[0].get("pending_ids")
    assert isinstance(pids, list) and len(pids) == 1
    run_starts = [e for e in ev1 if e.get("type") == "run_start"]
    assert run_starts
    run_id = str(run_starts[0].get("run_id") or "").strip()
    assert run_id

    def fake_stream_round1(*_a, **_kw):
        yield AgentContentDelta(text="Done.")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round1):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    ma = [e for e in ev2 if e.get("type") == "mutation_applied"]
    assert len(ma) == 1
    assert ma[0].get("name") == "mut_review"
    assert ma[0].get("pending_id") == pids[0]
    par = ma[0].get("post_apply_review")
    assert isinstance(par, dict)
    assert par.get("label") == "Manager review"
    assert par.get("path") == "/inbox"
    assert any(e.get("type") == "resume_start" for e in ev2)


def test_resume_defers_openai_loop_when_inbox_watches(monkeypatch) -> None:
    """After mutation confirm, inbox watches keep the run open and emit awaiting_inbox_review."""

    from hof.functions import function

    @function
    def mut_review() -> dict:
        """Mutation that ends in manager review."""
        return {"approval_status": "pending_review", "ok": True, "id": "exp-1"}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def post_apply(
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> PostApplyReviewHint | None:
        if result.get("approval_status") == "pending_review":
            return PostApplyReviewHint(
                label="Manager review",
                path="/inbox",
                url="http://localhost/inbox",
            )
        return None

    def inbox_watches(
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> list[InboxWatchDescriptor] | None:
        if result.get("approval_status") == "pending_review":
            return [
                InboxWatchDescriptor(
                    watch_id="watch-a",
                    record_type="expense",
                    record_id="exp-1",
                    label="Manager review",
                    path="/inbox",
                )
            ]
        return None

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_review"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            inbox_review_summary_mode="none",
            mutation_post_apply={"mut_review": post_apply},
            mutation_inbox_watches={"mut_review": inbox_watches},
            verify_inbox_watch=lambda _d: (True, "Approved."),
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_r",
            name="mut_review",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    ac = [e for e in ev1 if e.get("type") == "awaiting_confirmation"]
    assert len(ac) == 1
    pids = ac[0].get("pending_ids")
    assert isinstance(pids, list) and len(pids) == 1
    run_starts = [e for e in ev1 if e.get("type") == "run_start"]
    run_id = str(run_starts[0].get("run_id") or "").strip()
    assert run_id

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    assert any(e.get("type") == "mutation_applied" for e in ev2)
    air = [e for e in ev2 if e.get("type") == "awaiting_inbox_review"]
    assert len(air) == 1
    assert not any(e.get("type") == "resume_start" for e in ev2)
    ws = air[0].get("watches")
    assert isinstance(ws, list) and len(ws) == 1
    assert ws[0].get("watch_id") == "watch-a"

    saved = load_agent_run(run_id)
    assert saved is not None
    assert saved.get("open_inbox_watches")

    def fake_stream_after_inbox(*_a, **_kw):
        yield AgentContentDelta(text="After inbox.")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_after_inbox):
        ev3 = list(
            iter_agent_resume_inbox_stream(
                run_id,
                [{"watch_id": "watch-a"}],
            ),
        )

    assert any(e.get("type") == "resume_start" for e in ev3)
    fin = [e for e in ev3 if e.get("type") == "final"]
    assert fin
    assert "After inbox" in str(fin[0].get("reply") or "")


def test_inbox_review_summary_llm_streams_before_awaiting_inbox(monkeypatch) -> None:
    """Default inbox_review_summary_mode streams assistant guidance before awaiting_inbox_review."""

    from hof.functions import function

    @function
    def mut_review() -> dict:
        """Mutation that ends in manager review."""
        return {"approval_status": "pending_review", "ok": True, "id": "exp-1"}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def inbox_watches(
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> list[InboxWatchDescriptor] | None:
        if result.get("approval_status") == "pending_review":
            return [
                InboxWatchDescriptor(
                    watch_id="watch-sum",
                    record_type="expense",
                    record_id="exp-1",
                    label="Manager review",
                    path="/inbox?id=exp-1",
                )
            ]
        return None

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_review"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            mutation_inbox_watches={"mut_review": inbox_watches},
            verify_inbox_watch=lambda _d: (True, "ok"),
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_r",
            name="mut_review",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    def fake_inbox_summary(*_a, **_kw):
        yield AgentContentDelta(text="Please complete the Inbox review.")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    pids = [e for e in ev1 if e.get("type") == "awaiting_confirmation"][0].get("pending_ids")
    run_id = str([e for e in ev1 if e.get("type") == "run_start"][0].get("run_id") or "")

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_inbox_summary):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    phases = [e for e in ev2 if e.get("phase") == "inbox_review_summary"]
    assert phases, "expected inbox_review_summary phase before barrier"
    deltas = [e for e in ev2 if e.get("type") == "assistant_delta"]
    assert any("Inbox" in str(e.get("text") or "") for e in deltas)
    air = [e for e in ev2 if e.get("type") == "awaiting_inbox_review"]
    assert len(air) == 1

    saved = load_agent_run(run_id)
    assert saved is not None
    msgs = saved.get("oa_messages") or []
    assert any(
        m.get("role") == "assistant"
        and "Inbox" in str(m.get("content") or "")
        for m in msgs
        if isinstance(m, dict)
    )


def test_inbox_scan_after_inbox_resume_second_barrier(monkeypatch) -> None:
    """Chained pending_review rows after Inbox HITL can trigger another awaiting_inbox_review."""
    calls = {"n": 0}

    def scan_resume(
        resolved: list[InboxWatchDescriptor],
        baseline: frozenset[str],
    ) -> tuple[list[InboxWatchDescriptor], frozenset[str]]:
        calls["n"] += 1
        if calls["n"] == 1:
            assert len(resolved) == 1
            assert baseline == frozenset({"receipt-1", "other-pending"})
            return (
                [
                    InboxWatchDescriptor(
                        watch_id="watch-exp",
                        record_type="expense",
                        record_id="exp-11",
                        label="Expense review",
                        path="/inbox?id=exp-11",
                    ),
                ],
                frozenset({"receipt-1", "other-pending", "exp-11"}),
            )
        assert len(resolved) == 1
        assert resolved[0].watch_id == "watch-exp"
        return [], frozenset({"other-pending"})

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="test ",
            inbox_review_summary_mode="none",
            verify_inbox_watch=lambda _d: (True, "ok"),
            inbox_scan_after_inbox_resume=scan_resume,
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    rid = "run-chain-inbox-1"
    w1 = InboxWatchDescriptor(
        watch_id="watch-r",
        record_type="receipt_document",
        record_id="receipt-1",
        label="Receipt",
        path="/inbox?id=receipt-1",
    )
    save_agent_run(
        rid,
        {
            "oa_messages": [{"role": "user", "content": "hi"}],
            "model": "gpt-4o-mini",
            "llm_backend": "openai",
            "rounds": 1,
            "open_inbox_watches": [inbox_watch_to_wire(w1)],
            "inbox_pending_baseline_ids": ["other-pending", "receipt-1"],
        },
    )

    ev1 = list(
        iter_agent_resume_inbox_stream(
            rid,
            [{"watch_id": "watch-r"}],
        ),
    )
    air1 = [e for e in ev1 if e.get("type") == "awaiting_inbox_review"]
    assert len(air1) == 1
    assert air1[0].get("watches", [{}])[0].get("watch_id") == "watch-exp"
    assert not any(e.get("type") == "resume_start" for e in ev1)

    saved = load_agent_run(rid)
    assert saved is not None
    assert saved.get("inbox_pending_baseline_ids") == ["exp-11", "other-pending", "receipt-1"]

    def fake_stream_done(*_a, **_kw):
        yield AgentContentDelta(text="Done.")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_done):
        ev2 = list(
            iter_agent_resume_inbox_stream(
                rid,
                [{"watch_id": "watch-exp"}],
            ),
        )

    assert calls["n"] == 2
    assert any(e.get("type") == "resume_start" for e in ev2)
    assert any(e.get("type") == "final" for e in ev2)
    assert load_agent_run(rid) is None


def test_inbox_scan_after_mutations_adds_watches(monkeypatch) -> None:
    """inbox_scan_after_mutations can register watches without per-tool mutation_inbox_watches."""
    from hof.functions import function

    @function
    def mut_no_inbox() -> dict:
        return {"ok": True, "id": "x1"}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def scan(
        snap: set[str],
        batch: list[MutationBatchEntry],
        already: list[InboxWatchDescriptor],
    ) -> list[InboxWatchDescriptor]:
        assert snap == set()
        assert len(batch) == 1
        assert batch[0].function_name == "mut_no_inbox"
        assert batch[0].confirmed is True
        assert already == []
        return [
            InboxWatchDescriptor(
                watch_id="watch-scan",
                record_type="expense",
                record_id="exp-scan",
                label="From scan",
                path="/inbox",
            ),
        ]

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_no_inbox"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            inbox_review_summary_mode="none",
            inbox_snapshot_before_mutations=lambda: set(),
            inbox_scan_after_mutations=scan,
            verify_inbox_watch=lambda _d: (True, "ok"),
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_s",
            name="mut_no_inbox",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    ac = [e for e in ev1 if e.get("type") == "awaiting_confirmation"]
    pids = ac[0].get("pending_ids")
    run_id = str([e for e in ev1 if e.get("type") == "run_start"][0].get("run_id") or "")

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    air = [e for e in ev2 if e.get("type") == "awaiting_inbox_review"]
    assert len(air) == 1
    ws = air[0].get("watches")
    assert isinstance(ws, list) and len(ws) == 1
    assert ws[0].get("watch_id") == "watch-scan"
    assert not any(e.get("type") == "resume_start" for e in ev2)


def test_inbox_scan_merges_with_per_tool_watches(monkeypatch) -> None:
    """Scan can append watches alongside mutation_inbox_watches."""
    from hof.functions import function

    @function
    def mut_review() -> dict:
        return {"approval_status": "pending_review", "ok": True, "id": "exp-1"}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def inbox_watches(
        name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> list[InboxWatchDescriptor] | None:
        if result.get("approval_status") == "pending_review":
            return [
                InboxWatchDescriptor(
                    watch_id="watch-a",
                    record_type="expense",
                    record_id="exp-1",
                    label="Per tool",
                    path="/inbox",
                ),
            ]
        return None

    def scan(
        _snap: set[str],
        _batch: list[MutationBatchEntry],
        already: list[InboxWatchDescriptor],
    ) -> list[InboxWatchDescriptor]:
        assert len(already) == 1
        assert already[0].record_id == "exp-1"
        return [
            InboxWatchDescriptor(
                watch_id="watch-b",
                record_type="expense",
                record_id="exp-2",
                label="From scan",
                path="/inbox",
            ),
        ]

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_review"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            inbox_review_summary_mode="none",
            mutation_inbox_watches={"mut_review": inbox_watches},
            inbox_snapshot_before_mutations=lambda: set(),
            inbox_scan_after_mutations=scan,
            verify_inbox_watch=lambda _d: (True, "ok"),
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_r",
            name="mut_review",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    pids = [e for e in ev1 if e.get("type") == "awaiting_confirmation"][0].get("pending_ids")
    run_id = str([e for e in ev1 if e.get("type") == "run_start"][0].get("run_id") or "")

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    air = [e for e in ev2 if e.get("type") == "awaiting_inbox_review"]
    ws = air[0].get("watches")
    assert isinstance(ws, list) and len(ws) == 2
    ids = {w.get("watch_id") for w in ws}
    assert ids == {"watch-a", "watch-b"}


def test_inbox_scan_exception_still_allows_resume_when_no_watches(monkeypatch) -> None:
    """If inbox_scan_after_mutations raises, resume continues when no watches accumulated."""

    from hof.functions import function

    @function
    def mut_plain() -> dict:
        return {"ok": True}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    def scan_boom(
        _snap: set[str],
        _batch: list[MutationBatchEntry],
        _already: list[InboxWatchDescriptor],
    ) -> list[InboxWatchDescriptor]:
        msg = "scan failed"
        raise RuntimeError(msg)

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_plain"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
            inbox_snapshot_before_mutations=lambda: {"pre-existing"},
            inbox_scan_after_mutations=scan_boom,
            verify_inbox_watch=lambda _d: (True, "ok"),
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    def fake_stream_round0(*_a, **_kw):
        yield AgentToolCallDelta(
            index=0,
            tool_call_id="call_p",
            name="mut_plain",
            arguments="{}",
        )
        yield AgentMessageFinish(finish_reason="tool_calls", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_round0):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run"}], None),
        )

    pids = [e for e in ev1 if e.get("type") == "awaiting_confirmation"][0].get("pending_ids")
    run_id = str([e for e in ev1 if e.get("type") == "run_start"][0].get("run_id") or "")

    def fake_stream_after(*_a, **_kw):
        yield AgentContentDelta(text="Done.")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_after):
        ev2 = list(
            iter_agent_resume_stream(
                run_id,
                [{"pending_id": pids[0], "confirm": True}],
            ),
        )

    assert not any(e.get("type") == "awaiting_inbox_review" for e in ev2)
    assert any(e.get("type") == "resume_start" for e in ev2)


def test_configure_and_effective_allowlist() -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset({"a", "b"}),
            allowlist_mutation=frozenset({"c"}),
            system_prompt_intro="intro ",
        )
    )
    p = get_agent_policy()
    assert p.effective_allowlist() == frozenset({"a", "b", "c"} | BUILTIN_AGENT_TOOL_NAMES)


def test_collect_agent_chat_from_stream_final() -> None:
    def events():
        yield {"type": "run_start", "run_id": "r1", "model": "m1"}
        yield {"type": "final", "reply": "hi", "tool_rounds_used": 1, "model": "m1"}

    out = collect_agent_chat_from_stream(events())
    assert out["reply"] == "hi"
    assert out["tool_rounds_used"] == 1
    assert out["model"] == "m1"
    assert not out.get("error")


def test_iter_agent_chat_stream_passes_anthropic_output_config_effort(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")

    captured: list[dict] = []

    def _fake_stream_agent_turn(*_a, **kw):
        captured.append({k: v for k, v in kw.items() if k != "messages"})
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert len(captured) >= 1
    assert captured[0].get("output_config") == {"effort": "high"}


def test_iter_agent_chat_stream_openai_native_defaults_to_fallback_without_extras(
    monkeypatch,
) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)
    monkeypatch.delenv("AGENT_REASONING_OPENAI_EXTRAS", raising=False)

    def _fake_stream_agent_turn(*_a, reasoning, **_kw):
        assert reasoning.mode.value == "fallback"
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)


def test_iter_agent_chat_stream_openai_native_with_extras_merges_reasoning_effort(
    monkeypatch,
) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", "{}")

    seen: list = []

    def _fake_stream_agent_turn(*_a, reasoning, **_kw):
        seen.append(reasoning)
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert len(seen) == 1
    assert seen[0].mode.value == "native"
    assert seen[0].openai_extras == {"reasoning_effort": "high"}


def test_iter_agent_chat_stream_uses_anthropic_when_configured(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")

    backends: list[str] = []

    def _fake_stream_agent_turn(prov, backend, *_a, **_kw):
        backends.append(backend)
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert backends == ["anthropic"]


def test_iter_agent_chat_stream_anthropic_fallback_becomes_native_adaptive(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")
    monkeypatch.delenv("AGENT_ANTHROPIC_THINKING", raising=False)

    seen: list = []

    def _fake_stream_agent_turn(prov, backend, *_a, reasoning, **_kw):
        seen.append(reasoning)
        assert backend == "anthropic"
        assert reasoning.mode.value == "native"
        assert reasoning.anthropic_thinking == {"type": "adaptive"}
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert len(seen) == 1


def test_iter_agent_chat_stream_anthropic_native_respects_thinking_off(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "native")
    monkeypatch.setenv("AGENT_ANTHROPIC_THINKING", "off")

    captured: list[dict] = []

    def _fake_stream_agent_turn(*_a, reasoning, **kw):
        captured.append({k: v for k, v in kw.items() if k != "messages"})
        assert reasoning.anthropic_thinking is None
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert captured and "output_config" not in captured[0]


def test_iter_agent_chat_stream_rejects_openai_extras_with_anthropic(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("AGENT_REASONING_MODE", "native")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "anthropic" in str(ev[0].get("detail", "")).lower()


def test_iter_agent_chat_stream_uses_fallback_reasoning_mode(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")

    def _fake_stream_agent_turn(*_a, reasoning, **_kw):
        assert reasoning.mode.value == "fallback"
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=_fake_stream_agent_turn):
        ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert not any(x.get("type") == "error" for x in ev)
    assert any(x.get("type") == "run_start" for x in ev)


def test_iter_agent_chat_stream_rejects_fallback_with_openai_extras(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "fallback")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "AGENT_REASONING_OPENAI_EXTRAS" in str(ev[0].get("detail", ""))


def test_iter_agent_chat_stream_rejects_bad_reasoning_extras_json(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", "not-json")
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "AGENT_REASONING_OPENAI_EXTRAS" in str(ev[0].get("detail", ""))


def test_iter_agent_chat_stream_rejects_off_with_openai_extras(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AGENT_REASONING_MODE", "off")
    monkeypatch.setenv("AGENT_REASONING_OPENAI_EXTRAS", '{"reasoning_effort":"low"}')
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "off" in str(ev[0].get("detail", "")).lower()


def test_iter_agent_chat_stream_requires_api_key(monkeypatch) -> None:
    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset(),
            system_prompt_intro="x",
        )
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ev = list(iter_agent_chat_stream([{"role": "user", "content": "hello"}], None))
    assert ev and ev[0].get("type") == "error"
    assert "OPENAI_API_KEY" in str(ev[0].get("detail", ""))


def test_two_mutations_one_turn_then_mixed_resume(monkeypatch) -> None:
    """Two mutation tools in one model round → one barrier; resume applies mixed confirm/reject."""
    from hof.functions import function

    @function
    def mut_a() -> dict:
        """Mutation A."""
        return {"ok": True, "which": "a"}

    @function
    def mut_b() -> dict:
        """Mutation B."""
        return {"ok": True, "which": "b"}

    importlib.reload(importlib.import_module("hof.agent.builtin_tools"))

    configure_agent(
        AgentPolicy(
            allowlist_read=frozenset(),
            allowlist_mutation=frozenset({"mut_a", "mut_b"}),
            system_prompt_intro="test ",
            confirmation_summary_mode="none",
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_REASONING_MODE", raising=False)

    stream_calls: list[int] = []

    def fake_stream_agent_turn(*_a, **_kw):
        n = len(stream_calls)
        stream_calls.append(n)
        if n == 0:
            yield AgentToolCallDelta(
                index=0,
                tool_call_id="call_mut_a",
                name="mut_a",
                arguments="{}",
            )
            yield AgentToolCallDelta(
                index=1,
                tool_call_id="call_mut_b",
                name="mut_b",
                arguments="{}",
            )
            yield AgentMessageFinish(finish_reason="tool_calls", usage=None)
        else:
            yield AgentContentDelta(text="Continued after mixed resolutions.")
            yield AgentMessageFinish(finish_reason="stop", usage=None)

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_agent_turn):
        ev1 = list(
            iter_agent_chat_stream([{"role": "user", "content": "run two mutations"}], None),
        )

    mp = [e for e in ev1 if e.get("type") == "mutation_pending"]
    assert len(mp) == 2
    assert {e.get("name") for e in mp} == {"mut_a", "mut_b"}

    ac = [e for e in ev1 if e.get("type") == "awaiting_confirmation"]
    assert len(ac) == 1
    pids = ac[0].get("pending_ids")
    assert isinstance(pids, list) and len(pids) == 2

    rs = [e for e in ev1 if e.get("type") == "run_start"]
    assert rs
    run_id = str(rs[0].get("run_id") or "").strip()
    assert run_id

    resolutions = [
        {"pending_id": pids[0], "confirm": True},
        {"pending_id": pids[1], "confirm": False},
    ]

    with patch("hof.agent.stream.stream_agent_turn", side_effect=fake_stream_agent_turn):
        ev2 = list(iter_agent_resume_stream(run_id, resolutions))

    assert not any(e.get("type") == "error" for e in ev2)
    assert any(e.get("type") == "resume_start" for e in ev2)
    fin = [e for e in ev2 if e.get("type") == "final"]
    assert fin
    assert "Continued" in str(fin[0].get("reply") or "")
    assert stream_calls == [0, 1]


def test_agent_stream_error_event_maps_provider_failure() -> None:
    """Non-transient categories keep llm-markdown ``public_message`` on the wire."""
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    failure = ProviderFailure(
        category=ProviderFailureCategory.BAD_REQUEST,
        http_status=400,
        retry_after_seconds=None,
        public_message="Short user-facing message.",
        technical_detail="x",
    )
    exc = ProviderError("anthropic", "long internal message", failure=failure, retryable=False)
    d = _agent_stream_error_event(exc)
    assert d["type"] == "error"
    assert d["detail"] == "Short user-facing message."
    assert d["error_category"] == "bad_request"
    assert d["http_status"] == 400
    assert d["retryable"] is False
    assert "technical_detail" not in d


def test_agent_stream_error_event_rate_limit_uses_first_person_copy() -> None:
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    failure = ProviderFailure(
        category=ProviderFailureCategory.RATE_LIMIT,
        http_status=429,
        retry_after_seconds=16.0,
        public_message="IGNORED llm-markdown copy",
        technical_detail="x",
    )
    exc = ProviderError("anthropic", "internal", failure=failure, retryable=True)
    d = _agent_stream_error_event(exc)
    assert d["type"] == "error"
    assert "I hit a usage limit" in d["detail"]
    assert "IGNORED" not in d["detail"]
    assert "16" in d["detail"]


def test_agent_stream_error_event_after_engine_retries_exhausted() -> None:
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    failure = ProviderFailure(
        category=ProviderFailureCategory.RATE_LIMIT,
        http_status=429,
        retry_after_seconds=12.0,
        public_message="ignored for exhausted path",
        technical_detail="x",
    )
    exc = ProviderError("anthropic", "internal", failure=failure, retryable=True)
    d = _agent_stream_error_event(
        exc,
        engine_turn_retries_exhausted=True,
        engine_retry_max_attempts=3,
    )
    assert d["type"] == "error"
    assert "3 times" in d["detail"]
    assert "had to stop" in d["detail"].lower()
    assert "12" in d["detail"]
    assert d["retryable"] is False
    assert "technical_detail" not in d


def test_iter_stream_agent_turn_retries_when_only_segment_start_before_error(
    monkeypatch,
) -> None:
    """Agentic turns emit ``AgentSegmentStart`` before the provider opens the stream."""
    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentMessageFinish,
        AgentRateLimitWait,
        AgentSegmentStart,
    )
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    monkeypatch.setattr("hof.agent.stream.time.sleep", lambda _s: None)
    monkeypatch.setenv("HOF_AGENT_ENGINE_STREAM_ATTEMPTS", "2")

    calls = {"n": 0}

    def fake_turn(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] < 2:
            yield AgentSegmentStart(segment="reasoning")
            f = ProviderFailure(
                category=ProviderFailureCategory.RATE_LIMIT,
                http_status=429,
                retry_after_seconds=0.01,
                public_message="pm",
                technical_detail="t",
            )
            raise ProviderError("p", "m", failure=f, retryable=True)
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    monkeypatch.setattr("hof.agent.stream.stream_agent_turn", fake_turn)
    out = list(
        _iter_stream_agent_turn_with_engine_retries(
            None,
            "openai",
            [],
            model="m",
            tools=None,
            tool_choice=None,
        ),
    )
    assert calls["n"] == 2
    assert any(isinstance(e, AgentRateLimitWait) for e in out)
    assert any(
        isinstance(e, AgentContentDelta) and e.text == "ok" for e in out
    )


def test_iter_stream_agent_turn_engine_retries_then_succeeds(monkeypatch) -> None:
    from llm_markdown.agent_stream import (
        AgentContentDelta,
        AgentMessageFinish,
        AgentRateLimitWait,
    )
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    sleeps: list[float] = []
    monkeypatch.setattr("hof.agent.stream.time.sleep", lambda s: sleeps.append(float(s)))
    monkeypatch.setenv("HOF_AGENT_ENGINE_STREAM_ATTEMPTS", "3")

    calls = {"n": 0}

    def fake_turn(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] < 3:
            f = ProviderFailure(
                category=ProviderFailureCategory.RATE_LIMIT,
                http_status=429,
                retry_after_seconds=0.05,
                public_message="pm",
                technical_detail="t",
            )
            raise ProviderError("p", "m", failure=f, retryable=True)
        yield AgentContentDelta(text="ok")
        yield AgentMessageFinish(finish_reason="stop", usage=None)

    monkeypatch.setattr("hof.agent.stream.stream_agent_turn", fake_turn)
    out = list(
        _iter_stream_agent_turn_with_engine_retries(
            None,
            "openai",
            [],
            model="m",
            tools=None,
            tool_choice=None,
        ),
    )
    waits = [e for e in out if isinstance(e, AgentRateLimitWait)]
    assert len(waits) == 2
    assert len(sleeps) == 2
    assert any(isinstance(e, AgentContentDelta) for e in out)


def test_iter_stream_agent_turn_engine_retries_exhausted(monkeypatch) -> None:
    from llm_markdown.providers.base import ProviderError
    from llm_markdown.providers.failure_info import ProviderFailure, ProviderFailureCategory

    monkeypatch.setattr("hof.agent.stream.time.sleep", lambda _s: None)
    monkeypatch.setenv("HOF_AGENT_ENGINE_STREAM_ATTEMPTS", "3")

    def fake_turn(*_a, **_kw):
        f = ProviderFailure(
            category=ProviderFailureCategory.RATE_LIMIT,
            http_status=429,
            retry_after_seconds=0.01,
            public_message="pm",
            technical_detail="t",
        )
        raise ProviderError("p", "m", failure=f, retryable=True)

    monkeypatch.setattr("hof.agent.stream.stream_agent_turn", fake_turn)
    with pytest.raises(_AgentStreamTurnExhaustedError) as ei:
        list(
            _iter_stream_agent_turn_with_engine_retries(
                None,
                "openai",
                [],
                model="m",
                tools=None,
                tool_choice=None,
            ),
        )
    assert ei.value.attempts == 3
    assert isinstance(ei.value.cause, ProviderError)


def test_agent_stream_error_event_plain_exception() -> None:
    assert _agent_stream_error_event(ValueError("plain oops")) == {
        "type": "error",
        "detail": "plain oops",
    }
