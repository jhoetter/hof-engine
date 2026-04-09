/**
 * Plan mode (`agent_chat` with `mode: plan_discover`) — one status string for "what the agent is doing".
 *
 * **Source of truth:** server `discover_phase` on `{"type":"phase","phase":"model",...}` (see
 * `hof/agent/stream.py`). Observed `hof_builtin_present_plan_*` tool calls set ``planBuiltinLane``;
 * when set, that lane wins over ``discoverStreamPhase`` (the server can still report ``explore``
 * while the clarification builtin is building the questionnaire).
 *
 * This module is the only place that maps wire + UI phase → user-visible label. Do not duplicate
 * branching in `useMemo` elsewhere.
 */

import type { TFunction } from "i18next";

export type PlanDiscoverBuiltinLane = "clarification" | "plan" | null;

export type PlanDiscoverLiveLabelInput = {
  agentMode: "instant" | "plan";
  discoverStreamPhase: "explore" | "clarify" | "propose" | null;
  planPhase:
    | null
    | "generating"
    | "clarifying"
    | "ready"
    | "executing"
    | "done";
  /** Active plan builtin tool lane; takes precedence over ``discoverStreamPhase`` when both apply. */
  planBuiltinLane: PlanDiscoverBuiltinLane;
};

/** Maps live plan-discover row labels to settled keys (resolved via `t` at runtime). */
function liveToSettledKey(streamingLabel: string, t: TFunction<"hofEngine">): string | null {
  if (streamingLabel === t("planDiscover.exploring")) {
    return t("planDiscover.explored");
  }
  if (streamingLabel === t("planDiscover.generatingQuestions")) {
    return t("planDiscover.generatedQuestions");
  }
  if (streamingLabel === t("planDiscover.preparingPlan")) {
    return t("planDiscover.preparedPlan");
  }
  return null;
}

/** Shown next to the Questions card (active or review), not above the live assistant stream. */
export function isQuestionnaireLabel(
  label: string | null,
  t: TFunction<"hofEngine">,
): boolean {
  return (
    label != null &&
    (label === t("planDiscover.generatingQuestions") ||
      label === t("planDiscover.generatedQuestions"))
  );
}

/** Shown next to the Plan card, not above the live assistant stream. */
export function isPlanCardLabel(label: string | null, t: TFunction<"hofEngine">): boolean {
  return (
    label != null &&
    (label === t("planDiscover.preparingPlan") ||
      label === t("planDiscover.preparedPlan"))
  );
}

/** Shown above the live block list (explore / discovery prose). */
export function isLiveStreamLabel(label: string | null, t: TFunction<"hofEngine">): boolean {
  return (
    label != null &&
    (label === t("planDiscover.exploring") || label === t("planDiscover.explored"))
  );
}

/** Past-tense label for the status row after a plan-discover phase settles. */
export function settleLiveLabel(streamingLabel: string, t: TFunction<"hofEngine">): string {
  return liveToSettledKey(streamingLabel, t) ?? streamingLabel;
}

/**
 * Live label while the plan-discover stream is active (`busy` and plan mode). Does not read
 * ``busy`` — callers should only use this while the request is in flight or in the same tick
 * before idle cleanup clears discover state.
 */
export function computeLiveLabel(
  input: PlanDiscoverLiveLabelInput,
  t: TFunction<"hofEngine">,
): string | null {
  if (input.agentMode !== "plan") {
    return null;
  }
  const { planPhase, discoverStreamPhase } = input;

  if (planPhase === "clarifying") {
    return settleLiveLabel(t("planDiscover.generatingQuestions"), t);
  }
  if (planPhase === "generating") {
    return t("planDiscover.preparingPlan");
  }
  if (
    planPhase === "ready" ||
    planPhase === "executing" ||
    planPhase === "done"
  ) {
    return null;
  }

  if (input.planBuiltinLane === "clarification") {
    return t("planDiscover.generatingQuestions");
  }
  if (input.planBuiltinLane === "plan") {
    return t("planDiscover.preparingPlan");
  }

  switch (discoverStreamPhase) {
    case "explore":
      return t("planDiscover.exploring");
    case "clarify":
      return t("planDiscover.generatingQuestions");
    case "propose":
      return t("planDiscover.preparingPlan");
    default:
      break;
  }

  return null;
}

/**
 * Maps a server ``discover_phase`` to the user-visible label string. Used to stamp
 * ``reasoningLabelRef`` synchronously when the NDJSON event arrives, before React commits
 * ``discoverStreamPhase`` state.
 */
export function discoverPhaseToLabel(
  dp: "explore" | "clarify" | "propose" | null,
  t: TFunction<"hofEngine">,
): string | null {
  switch (dp) {
    case "explore":
      return t("planDiscover.exploring");
    case "clarify":
      return t("planDiscover.generatingQuestions");
    case "propose":
      return t("planDiscover.preparingPlan");
    default:
      return null;
  }
}
