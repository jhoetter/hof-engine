"""Tests for plan_types clarification / proposal parsing."""

from __future__ import annotations

import json

from hof.agent.plan_types import (
    parse_plan_clarification_questions,
    validate_plan_clarification_answers,
)


def test_parse_plan_clarification_rejects_missing_options() -> None:
    """Questions without options must fail so the model can retry with real choices."""
    payload = {
        "questions": [
            {
                "key": "depreciation_scope",
                "label": "Welche Ausgaben sollen abgeschrieben werden?",
                "hint": "Möchten Sie alle Equipment-Ausgaben abschreiben?",
                "required": True,
            },
        ],
    }
    out, err = parse_plan_clarification_questions(json.dumps(payload))
    assert out is None
    assert err is not None
    # Error message must reference options so the model knows what to fix.
    assert "options" in err.lower() or "min_length" in err.lower() or "2" in err


def test_parse_plan_clarification_questions_json_key_with_choices() -> None:
    """Model sends ``questions_json`` with ``question``/``choices``/``value`` shape."""
    payload = {
        "questions_json": [
            {
                "key": "depreciation_scope",
                "question": "Welche Ausgaben sollen abgeschrieben werden?",
                "question_type": "single_choice",
                "choices": [
                    {"value": "all", "label": "Alle Ausgaben (10 Positionen)"},
                    {"value": "equipment", "label": "Nur Equipment"},
                ],
            },
            {
                "key": "method",
                "question": "Welche Methode?",
                "question_type": "multiple_choice",
                "choices": [
                    {"value": "linear", "label": "Linear"},
                    {"value": "degressive", "label": "Degressiv"},
                ],
            },
        ],
    }
    out, err = parse_plan_clarification_questions(json.dumps(payload))
    assert err is None, err
    assert out is not None
    assert len(out) == 2
    q0 = out[0]
    assert q0["id"] == "depreciation_scope"
    assert "Welche Ausgaben" in q0["prompt"]
    assert q0["allow_multiple"] is False
    opt_ids = [o["id"] for o in q0["options"]]
    assert "all" in opt_ids
    assert "equipment" in opt_ids
    q1 = out[1]
    assert q1["allow_multiple"] is True


def test_parse_plan_clarification_still_accepts_canonical_shape() -> None:
    payload = {
        "questions": [
            {
                "id": "q1",
                "prompt": "Pick one",
                "options": [
                    {"id": "a", "label": "A"},
                    {"id": "b", "label": "B"},
                ],
                "allow_multiple": False,
            },
        ],
    }
    out, err = parse_plan_clarification_questions(json.dumps(payload))
    assert err is None
    assert out is not None
    assert out[0]["id"] == "q1"
    assert out[0]["prompt"] == "Pick one"
    opts = out[0]["options"]
    assert len(opts) == 3
    assert any(o.get("is_other") for o in opts)
    assert any(o["label"] == "Other / specify" for o in opts)


def test_validate_plan_clarification_answers_uses_is_other_flag() -> None:
    questions = [
        {
            "id": "q1",
            "prompt": "Pick",
            "options": [
                {"id": "a", "label": "A", "is_other": False},
                {"id": "custom", "label": "Custom", "is_other": True},
            ],
            "allow_multiple": False,
        },
    ]
    sel, other, err = validate_plan_clarification_answers(
        questions,
        [
            {
                "question_id": "q1",
                "selected_option_ids": ["custom"],
                "other_text": "details",
            },
        ],
    )
    assert err is None
    assert sel == {"q1": ["custom"]}
    assert other == {"q1": "details"}


def test_validate_plan_clarification_answers_uses_is_other_false() -> None:
    """Option id without ``other`` substring does not require other_text when not is_other."""
    questions = [
        {
            "id": "q1",
            "prompt": "Pick",
            "options": [
                {"id": "a", "label": "A", "is_other": False},
                {"id": "custom", "label": "Custom", "is_other": False},
            ],
            "allow_multiple": False,
        },
    ]
    sel, other, err = validate_plan_clarification_answers(
        questions,
        [
            {
                "question_id": "q1",
                "selected_option_ids": ["custom"],
            },
        ],
    )
    assert err is None
    assert sel == {"q1": ["custom"]}
    assert other == {}
