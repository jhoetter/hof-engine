/**
 * Single source of truth for **where** the plan-discover status row appears and **which timer**
 * drives it. Label resolution stays in {@link planDiscoverStatusLabel}; this layer only maps
 * display strings + UI flags → placement (one surface at a time).
 */

import type { TFunction } from "i18next";
import {
  isLiveStreamLabel,
  isPlanCardLabel,
  isQuestionnaireLabel,
} from "./planDiscoverStatusLabel";

export type PlanDiscoverPlacement =
  | "none"
  | "above_live_stream"
  | "above_questionnaire"
  | "above_plan";

/**
 * - `thinking_episode`: global model round clock (explore / early wait).
 * - `clarification_generation`: wall-clock from clarification tool_call to barrier.
 * - `plan_preparation`: wall-clock from plan tool_call to plan card visible.
 */
export type PlanDiscoverTimerKind =
  | "thinking_episode"
  | "clarification_generation"
  | "plan_preparation";

export type PlanDiscoverUiState = {
  placement: PlanDiscoverPlacement;
  /** Shimmer/tertiary label; null means generic "Thinking" for the `above_live_stream` placement. */
  label: string | null;
  timerKind: PlanDiscoverTimerKind | null;
};

/**
 * Derives **one** status row for plan mode: questionnaire and plan labels sit next to their cards
 * when those cards exist; otherwise the same semantic phase uses the `above_live_stream` placement with
 * Thinking + the thinking-episode timer (no duplicate questionnaire copy above the stream).
 */
export function computePlanDiscoverUiState(p: {
  agentMode: "instant" | "plan";
  busy: boolean;
  /** {@link HofAgentChatContextValue.streamingReasoningLabel} */
  displayLabel: string | null;
  hasQuestionnaireCard: boolean;
  showPlanCard: boolean;
  /** Used so Instant mode only hoists "Thinking" before the first block (matches legacy UI). */
  liveBlocksLength: number;
  /**
   * Clarify phase without barrier yet: builtin ``tool_call`` and/or server ``discover_phase:
   * clarify`` — questionnaire-slot status row + skeleton instead of live-stream status row.
   */
  pendingQuestionnaireGeneration?: boolean;
  t: TFunction<"hofEngine">;
}): PlanDiscoverUiState {
  if (p.agentMode !== "plan") {
    if (!p.busy) {
      return { placement: "none", label: null, timerKind: null };
    }
    if (p.liveBlocksLength === 0) {
      return {
        placement: "above_live_stream",
        label: null,
        timerKind: "thinking_episode",
      };
    }
    return { placement: "none", label: null, timerKind: null };
  }

  if (p.pendingQuestionnaireGeneration) {
    return {
      placement: "above_questionnaire",
      label: null,
      timerKind: "clarification_generation",
    };
  }

  const dl = p.displayLabel;
  const { t } = p;

  if (dl && isQuestionnaireLabel(dl, t)) {
    if (p.hasQuestionnaireCard) {
      return {
        placement: "above_questionnaire",
        label: dl,
        timerKind: "clarification_generation",
      };
    }
    return {
      placement: "above_live_stream",
      label: null,
      timerKind: p.busy ? "thinking_episode" : null,
    };
  }

  if (dl && isPlanCardLabel(dl, t)) {
    if (p.showPlanCard) {
      return {
        placement: "above_plan",
        label: dl,
        timerKind: "plan_preparation",
      };
    }
    return {
      placement: "above_live_stream",
      label: null,
      timerKind: p.busy ? "thinking_episode" : null,
    };
  }

  if (dl && isLiveStreamLabel(dl, t)) {
    return {
      placement: "above_live_stream",
      label: dl,
      timerKind: "thinking_episode",
    };
  }

  if (p.busy) {
    if (p.liveBlocksLength > 0) {
      return { placement: "none", label: null, timerKind: null };
    }
    return {
      placement: "above_live_stream",
      label: null,
      timerKind: "thinking_episode",
    };
  }

  return { placement: "none", label: null, timerKind: null };
}
