"""Typed models for plan-mode clarification, plan proposals, and barrier state.

Used by ``stream.py`` for validation and by ``conversation_state.py`` for persistence.
Mirrors the TypeScript ``PlanClarificationQuestion`` / ``PlanClarificationBarrierV1``
types in ``hof-react``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlanClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class PlanClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    options: list[PlanClarificationOption] = Field(min_length=2, max_length=5)
    allow_multiple: bool = False

    @field_validator("options")
    @classmethod
    def _ensure_other_option(
        cls, v: list[PlanClarificationOption],
    ) -> list[PlanClarificationOption]:
        has_other = any("other" in o.id.lower() for o in v)
        if not has_other:
            idx = len(v)
            v.append(PlanClarificationOption(id=f"q{idx}_other", label="Andere / eigene Angabe"))
        return v


class PlanClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question_id: str = Field(alias="questionId")
    selected_option_ids: list[str] = Field(min_length=1, alias="selectedOptionIds")
    other_text: str = Field(default="", alias="otherText")


class PlanClarificationBarrierV1(BaseModel):
    """Persisted barrier state for a paused plan-discover run."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    run_id: str = Field(alias="runId")
    clarification_id: str = Field(alias="clarificationId")
    questions: list[PlanClarificationQuestion]


class PlanStep(BaseModel):
    """A single actionable step in a plan proposal."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=300)


class PlanProposal(BaseModel):
    """Structured plan produced by ``hof_builtin_present_plan``."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=800, default="")
    steps: list[PlanStep] = Field(min_length=1, max_length=30)


def plan_proposal_to_markdown(proposal: PlanProposal) -> str:
    """Render a validated plan proposal as deterministic GFM markdown."""
    parts = [f"# {proposal.title}"]
    if proposal.description:
        parts.append("")
        parts.append(proposal.description)
    parts.append("")
    for step in proposal.steps:
        parts.append(f"- [ ] {step.label}")
    return "\n".join(parts)


def parse_plan_proposal(
    arguments_json: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse and validate tool arguments for ``hof_builtin_present_plan``.

    Returns ``(proposal_dict, None)`` on success or ``(None, error)`` on failure.
    The returned dict has keys ``title``, ``description``, ``steps``.
    """
    import json as _json

    try:
        parsed = _json.loads(arguments_json or "{}")
    except _json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "arguments must be a JSON object"

    raw_steps = parsed.get("steps")
    if isinstance(raw_steps, str):
        try:
            raw_steps = _json.loads(raw_steps)
        except _json.JSONDecodeError:
            pass
    if isinstance(raw_steps, list):
        parsed["steps"] = raw_steps

    try:
        validated = PlanProposal.model_validate(parsed)
    except Exception as exc:
        return None, f"plan proposal validation failed: {exc}"
    return validated.model_dump(), None


def _normalize_plan_clarification_option_dict(o: Any) -> dict[str, str] | None:
    """Map common option aliases to ``id`` / ``label``."""
    if not isinstance(o, dict):
        return None
    oid = o.get("id") or o.get("key") or o.get("value")
    lab = o.get("label") or o.get("text") or o.get("title")
    if oid is None or lab is None:
        if oid is not None and lab is None:
            lab = oid
        else:
            return None
    sid = str(oid).strip()
    slb = str(lab).strip()
    if not sid or not slb:
        return None
    return {"id": sid, "label": slb}


def _normalize_plan_clarification_question_dict(
    q: Any,
    index: int,
) -> dict[str, Any]:
    """Map alternate LLM shapes (``key``/``label``/``hint``) to the wire schema.

    Returns a dict ready for Pydantic validation.  If ``options`` are missing or
    fewer than 2 the dict will fail Pydantic's ``min_length=2`` check — the
    caller surfaces that error as a tool result so the model can retry with
    proper choices rather than presenting the user with a synthetic fallback.
    """
    if not isinstance(q, dict):
        return {}
    raw = dict(q)
    qid_raw = raw.get("id") or raw.get("key")
    if qid_raw is not None and str(qid_raw).strip():
        qid = str(qid_raw).strip()
    else:
        qid = f"q{index}"

    prompt = raw.get("prompt") or raw.get("question")
    if isinstance(prompt, str) and prompt.strip():
        prompt_s = prompt.strip()
    else:
        label = str(raw.get("label") or "").strip()
        hint = str(raw.get("hint") or "").strip()
        if label and hint:
            prompt_s = f"{label}\n\n{hint}"
        elif label:
            prompt_s = label
        elif hint:
            prompt_s = hint
        else:
            prompt_s = f"Question {index + 1}"

    raw_opts = raw.get("options")
    if isinstance(raw_opts, str):
        import json as _json

        try:
            raw_opts = _json.loads(raw_opts)
        except _json.JSONDecodeError:
            raw_opts = []
    if raw_opts is None:
        raw_opts = raw.get("choices") or raw.get("answers")
    if not isinstance(raw_opts, list):
        raw_opts = []

    qt = str(raw.get("question_type") or "").strip().lower()
    if qt == "multiple_choice":
        allow_multiple_from_type = True
    elif qt:
        allow_multiple_from_type = False
    else:
        allow_multiple_from_type = None

    normalized_opts: list[dict[str, str]] = []
    for o in raw_opts:
        nd = _normalize_plan_clarification_option_dict(o)
        if nd is not None:
            normalized_opts.append(nd)

    if allow_multiple_from_type is not None:
        allow_multiple = allow_multiple_from_type
    else:
        allow_multiple = bool(raw.get("allow_multiple", False))

    return {
        "id": qid,
        "prompt": prompt_s,
        "options": normalized_opts,
        "allow_multiple": allow_multiple,
    }


def parse_plan_clarification_questions(
    arguments_json: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Parse and validate the ``questions`` argument from the clarification tool.

    Returns ``(questions_dicts, None)`` on success or ``(None, error_message)``
    on failure. The returned dicts use the same wire shape
    (``id``, ``prompt``, ``options``, ``allow_multiple``).
    """
    import json as _json

    try:
        parsed = _json.loads(arguments_json or "{}")
    except _json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, "arguments must be a JSON object"
    raw_q = parsed.get("questions") or parsed.get("questions_json")
    if isinstance(raw_q, str):
        try:
            raw_q = _json.loads(raw_q)
        except _json.JSONDecodeError:
            pass
    if not isinstance(raw_q, list) or len(raw_q) < 1:
        return None, "questions must be a non-empty array"
    out: list[dict[str, Any]] = []
    for i, q in enumerate(raw_q):
        try:
            normalized = _normalize_plan_clarification_question_dict(q, i)
            validated = PlanClarificationQuestion.model_validate(normalized)
        except Exception as exc:
            return None, f"questions[{i}]: {exc}"
        out.append(validated.model_dump())
    return out, None


def validate_plan_clarification_answers(
    questions: list[dict[str, Any]],
    answers: list[Any],
) -> tuple[dict[str, list[str]] | None, dict[str, str], str | None]:
    """Validate user answers against the original questions.

    Returns ``(selections_by_qid, other_text_by_qid, None)`` on success
    or ``(None, {}, error_message)`` on failure.
    """
    if not isinstance(answers, list):
        return None, {}, "answers must be a list"
    qmap = {str(q["id"]): q for q in questions}
    out: dict[str, list[str]] = {}
    other_text_by_qid: dict[str, str] = {}
    for i, a in enumerate(answers):
        if not isinstance(a, dict):
            return None, {}, f"answers[{i}] must be object"
        qid = str(a.get("question_id") or a.get("questionId") or "").strip()
        sel = a.get("selected_option_ids") or a.get("selectedOptionIds")
        if not qid or qid not in qmap:
            return None, {}, f"unknown question_id: {qid!r}"
        if not isinstance(sel, list):
            return None, {}, f"selected_option_ids must be array for {qid!r}"
        oids = [str(x).strip() for x in sel if str(x).strip()]
        allowed = {o["id"] for o in qmap[qid]["options"]}
        for oid in oids:
            if oid not in allowed:
                return None, {}, f"invalid option id {oid!r} for question {qid!r}"
        if not qmap[qid]["allow_multiple"] and len(oids) > 1:
            return None, {}, f"question {qid!r} allows only one option"
        if len(oids) < 1:
            return None, {}, f"question {qid!r} requires at least one selected option"
        raw_other = a.get("other_text") or a.get("otherText")
        other_t = str(raw_other).strip() if raw_other is not None else ""
        has_other_option = any("other" in oid.lower() for oid in oids)
        if has_other_option and not other_t:
            return (
                None,
                {},
                f"question {qid!r}: other_text is required when an Other option is selected",
            )
        if other_t and not has_other_option:
            return (
                None,
                {},
                f"question {qid!r}: other_text is only allowed when an Other option is selected",
            )
        if other_t:
            other_text_by_qid[qid] = other_t
        out[qid] = oids
    if set(out.keys()) != set(qmap.keys()):
        return None, {}, "each question must be answered exactly once"
    return out, other_text_by_qid, None
