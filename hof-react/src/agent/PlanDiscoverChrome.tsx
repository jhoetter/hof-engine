"use client";

import { AgentEarlyThinkingIndicator } from "./HofAgentChatBlocks";

export type PlanDiscoverChromeProps = {
  label?: string;
  liveFormatted?: string | null;
  settledFormatted?: string | null;
};

/**
 * Single plan-discover status row (shimmer + optional duration). Placement is chosen by the
 * parent from {@link computePlanDiscoverUiState}; only one instance should be visible at a time.
 */
export function PlanDiscoverChrome({
  label,
  liveFormatted,
  settledFormatted,
}: PlanDiscoverChromeProps) {
  /**
   * Horizontal inset is applied once by the parent ({@link HofAgentMessages} live stream column,
   * {@link PlanQuestionnaireSection}, {@link PlanCardSection}) so the status row lines up with
   * assistant blocks and cards.
   */
  return (
    <AgentEarlyThinkingIndicator
      label={label}
      liveFormatted={liveFormatted}
      settledFormatted={settledFormatted}
    />
  );
}
