/**
 * Plan mode (`agent_chat` with `mode: plan_discover`) — one status string for “what the agent is doing”.
 *
 * **Source of truth:** server `discover_phase` on `{"type":"phase","phase":"model",...}` (see
 * `hof/agent/stream.py`). Observed `hof_builtin_present_plan_*` tool calls set ``planBuiltinLane``;
 * when set, that lane wins over ``discoverStreamPhase`` (the server can still report ``explore``
 * while the clarification builtin is building the questionnaire).
 *
 * This module is the only place that maps wire + UI phase → user-visible label. Do not duplicate
 * branching in `useMemo` elsewhere.
 *
 * **Persistence:** while ``busy`` is false, the UI shows {@link resolvePlanDiscoverStatusDisplayLabel}
 * with a settled string copied from the last live label at idle (see provider).
 */

export type PlanDiscoverBuiltinLane = "clarification" | "plan" | null;

export type PlanDiscoverStatusInput = {
  busy: boolean;
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

/** Maps live plan-discover row labels to past-tense settled strings (aligned with thinking UI). */
const LIVE_TO_SETTLED: Record<string, string> = {
  Exploring: "Explored",
  "Generating questions": "Generated questions",
  "Preparing plan": "Prepared plan",
};

const QUESTIONNAIRE_STATUS_LABELS = new Set<string>([
  "Generating questions",
  "Generated questions",
]);

const PLAN_CARD_STATUS_LABELS = new Set<string>([
  "Preparing plan",
  "Prepared plan",
]);

const LIVE_STREAM_STATUS_LABELS = new Set<string>(["Exploring", "Explored"]);

/** Shown next to the Questions card (active or review), not above the live assistant stream. */
export function isQuestionnairePlanDiscoverStatusLabel(
  label: string | null,
): boolean {
  return label != null && QUESTIONNAIRE_STATUS_LABELS.has(label);
}

/** Shown next to the Plan card, not above the live assistant stream. */
export function isPlanCardPlanDiscoverStatusLabel(
  label: string | null,
): boolean {
  return label != null && PLAN_CARD_STATUS_LABELS.has(label);
}

/** Shown above the live block list (explore / discovery prose). */
export function isLiveStreamPlanDiscoverStatusLabel(
  label: string | null,
): boolean {
  return label != null && LIVE_STREAM_STATUS_LABELS.has(label);
}

/**
 * When true, {@link ReasoningStreamPeek} should not repeat a stamped block ``reasoningLabel`` that
 * already appears on the questionnaire or plan card row.
 */
export function shouldSuppressPlanDiscoverStampedLabel(
  label: string | null | undefined,
  questionnaireCardVisible: boolean,
  planCardVisibleForPeek: boolean,
): boolean {
  const trimmed = label?.trim();
  if (!trimmed) {
    return false;
  }
  if (
    questionnaireCardVisible &&
    isQuestionnairePlanDiscoverStatusLabel(trimmed)
  ) {
    return true;
  }
  if (planCardVisibleForPeek && isPlanCardPlanDiscoverStatusLabel(trimmed)) {
    return true;
  }
  return false;
}

/**
 * Past-tense label for the status row after a plan-discover phase settles.
 * Kept in sync with ``settledReasoningLabel`` in ``HofAgentChatBlocks``.
 */
export function settlePlanDiscoverLiveLabel(streamingLabel: string): string {
  return LIVE_TO_SETTLED[streamingLabel] ?? streamingLabel;
}

/**
 * Live label while the plan-discover stream is active (`busy` and plan mode). Does not read
 * ``busy`` — callers should only use this while the request is in flight or in the same tick
 * before idle cleanup clears discover state.
 */
export function computePlanDiscoverLiveLabel(
  input: Omit<PlanDiscoverStatusInput, "busy">,
): string | null {
  if (input.agentMode !== "plan") {
    return null;
  }
  const { planPhase, discoverStreamPhase } = input;

  if (planPhase === "clarifying") {
    return settlePlanDiscoverLiveLabel("Generating questions");
  }
  if (planPhase === "generating") {
    return "Preparing plan";
  }
  if (
    planPhase === "ready" ||
    planPhase === "executing" ||
    planPhase === "done"
  ) {
    return null;
  }

  if (input.planBuiltinLane === "clarification") {
    return "Generating questions";
  }
  if (input.planBuiltinLane === "plan") {
    return "Preparing plan";
  }

  switch (discoverStreamPhase) {
    case "explore":
      return "Exploring";
    case "clarify":
      return "Generating questions";
    case "propose":
      return "Preparing plan";
    default:
      break;
  }

  return null;
}

/**
 * Label for plan-discover status (early row before first block; reasoning peek row; and during
 * reply streaming in ``AssistantSegmentedBody`` when reasoning is no longer live).
 * Returns `null` when no plan-discover-specific status applies.
 *
 * **Legacy:** only non-null while ``busy`` — use {@link computePlanDiscoverLiveLabel} +
 * {@link resolvePlanDiscoverStatusDisplayLabel} for settled idle labels.
 */
export function computePlanDiscoverStatusLabel(
  input: PlanDiscoverStatusInput,
): string | null {
  if (!input.busy || input.agentMode !== "plan") {
    return null;
  }
  return computePlanDiscoverLiveLabel(input);
}

/**
 * Display string: live while ``busy``; otherwise the last settled plan-discover label persisted by
 * the chat provider (cleared on ``run_start`` / ``resume_start`` / leaving plan mode).
 */
export function resolvePlanDiscoverStatusDisplayLabel(
  input: PlanDiscoverStatusInput,
  persistedPlanDiscoverLabel: string | null,
): string | null {
  if (input.agentMode !== "plan") {
    return null;
  }
  if (input.busy) {
    return computePlanDiscoverLiveLabel(input);
  }
  return persistedPlanDiscoverLabel;
}

/**
 * Stamped synchronously on `phase: model` before React commits `discoverStreamPhase` state
 * (mirrors {@link computePlanDiscoverLiveLabel} for discover segments only).
 */
export function discoverPhaseToEagerLabel(
  dp: "explore" | "clarify" | "propose" | null,
): string | null {
  switch (dp) {
    case "explore":
      return "Exploring";
    case "clarify":
      return "Generating questions";
    case "propose":
      return "Preparing plan";
    default:
      return null;
  }
}
