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

/**
 * Label for plan-discover status (early row before first block; reasoning peek row; and during
 * reply streaming in ``AssistantSegmentedBody`` when reasoning is no longer live).
 * Returns `null` when no plan-discover-specific status applies.
 */
export function computePlanDiscoverStatusLabel(
  input: PlanDiscoverStatusInput,
): string | null {
  if (!input.busy || input.agentMode !== "plan") {
    return null;
  }
  const { planPhase, discoverStreamPhase } = input;

  if (planPhase === "clarifying") {
    return null;
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

  // ``discover_phase`` can lag behind ``tool_call`` (e.g. still ``explore`` while clarification runs).
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
 * Stamped synchronously on `phase: model` before React commits `discoverStreamPhase` state
 * (mirrors {@link computePlanDiscoverStatusLabel} for discover segments only).
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
