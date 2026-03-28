/**
 * Single source of truth for **where** plan-discover chrome appears and **which timer** drives it.
 * {@link computePlanDiscoverLiveLabel} / display labels stay in {@link planDiscoverStatusLabel};
 * this layer only maps display strings + UI flags → placement (one surface at a time).
 */

import {
  isLiveStreamPlanDiscoverStatusLabel,
  isPlanCardPlanDiscoverStatusLabel,
  isQuestionnairePlanDiscoverStatusLabel,
} from "./planDiscoverStatusLabel";

export type PlanDiscoverChromePlacement =
  | "none"
  | "above_live_stream"
  | "above_questionnaire"
  | "above_plan";

/** Which UI region owns the single plan-discover chrome row (mirrors {@link PlanDiscoverChromePlacement}). */
export type PlanDiscoverUiOwner =
  | "none"
  | "live_stream"
  | "questionnaire"
  | "plan";

export function planDiscoverOwnerFromPlacement(
  placement: PlanDiscoverChromePlacement,
): PlanDiscoverUiOwner {
  if (placement === "none") {
    return "none";
  }
  if (placement === "above_live_stream") {
    return "live_stream";
  }
  if (placement === "above_questionnaire") {
    return "questionnaire";
  }
  return "plan";
}

/**
 * - `thinking_episode`: global model round clock (explore / early wait / questionnaire-or-plan wait before card).
 * - `clarification_generation`: {@link clarificationGenerationStartedAtMs}.
 * - `plan_preparation`: {@link planPreparationStartedAtMs}.
 */
export type PlanDiscoverTimerKind =
  | "thinking_episode"
  | "clarification_generation"
  | "plan_preparation";

export type PlanDiscoverUiState = {
  placement: PlanDiscoverChromePlacement;
  /** Stable owner id for tests/docs; use with {@link PlanQuestionnaireSection} / {@link PlanCardSection}. */
  owner: PlanDiscoverUiOwner;
  /** Shimmer/tertiary label; null means generic “Thinking” for {@link above_live_stream}. */
  label: string | null;
  timerKind: PlanDiscoverTimerKind | null;
};

/**
 * Derives **one** chrome row for plan mode: questionnaire and plan labels sit next to their cards
 * when those cards exist; otherwise the same semantic phase uses {@link above_live_stream} with
 * Thinking + the thinking-episode timer (no duplicate questionnaire copy above the stream).
 */
export function computePlanDiscoverUiState(p: {
  agentMode: "instant" | "plan";
  busy: boolean;
  /** {@link HofAgentChatContextValue.streamingReasoningLabel} */
  displayLabel: string | null;
  hasQuestionnaireCard: boolean;
  showPlanCard: boolean;
  /** Used so Instant mode only hoists “Thinking” before the first block (matches legacy UI). */
  liveBlocksLength: number;
  /**
   * Clarify phase without barrier yet: builtin ``tool_call`` and/or server ``discover_phase:
   * clarify`` — questionnaire-slot chrome + skeleton instead of live-stream chrome.
   */
  pendingQuestionnaireGeneration?: boolean;
}): PlanDiscoverUiState {
  if (p.agentMode !== "plan") {
    if (!p.busy) {
      return {
        placement: "none",
        owner: "none",
        label: null,
        timerKind: null,
      };
    }
    if (p.liveBlocksLength === 0) {
      return {
        placement: "above_live_stream",
        owner: "live_stream",
        label: null,
        timerKind: "thinking_episode",
      };
    }
    return {
      placement: "none",
      owner: "none",
      label: null,
      timerKind: null,
    };
  }

  if (p.pendingQuestionnaireGeneration) {
    return {
      placement: "above_questionnaire",
      owner: "questionnaire",
      label: null,
      timerKind: "clarification_generation",
    };
  }

  const dl = p.displayLabel;

  if (dl && isQuestionnairePlanDiscoverStatusLabel(dl)) {
    if (p.hasQuestionnaireCard) {
      return {
        placement: "above_questionnaire",
        owner: "questionnaire",
        label: dl,
        timerKind: "clarification_generation",
      };
    }
    return {
      placement: "above_live_stream",
      owner: "live_stream",
      label: null,
      timerKind: p.busy ? "thinking_episode" : null,
    };
  }

  if (dl && isPlanCardPlanDiscoverStatusLabel(dl)) {
    if (p.showPlanCard) {
      return {
        placement: "above_plan",
        owner: "plan",
        label: dl,
        timerKind: "plan_preparation",
      };
    }
    return {
      placement: "above_live_stream",
      owner: "live_stream",
      label: null,
      timerKind: p.busy ? "thinking_episode" : null,
    };
  }

  if (dl && isLiveStreamPlanDiscoverStatusLabel(dl)) {
    return {
      placement: "above_live_stream",
      owner: "live_stream",
      label: dl,
      timerKind: "thinking_episode",
    };
  }

  if (p.busy) {
    if (p.liveBlocksLength > 0) {
      return {
        placement: "none",
        owner: "none",
        label: null,
        timerKind: null,
      };
    }
    return {
      placement: "above_live_stream",
      owner: "live_stream",
      label: null,
      timerKind: "thinking_episode",
    };
  }

  return {
    placement: "none",
    owner: "none",
    label: null,
    timerKind: null,
  };
}
