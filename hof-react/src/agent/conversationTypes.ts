/**
 * Versioned document stored in the app database (e.g. JSONB) and validated server-side
 * by ``hof.agent.AgentConversationStateV1``.
 *
 * ``thread`` / ``draft.liveBlocks`` are the same shapes as ``HofAgentChat`` internal blocks
 * (serialized with ``structuredClone`` / JSON).
 */
export type AgentConversationDraftV1 = {
  liveBlocks: unknown[];
  approvalBarrier: {
    runId: string;
    items: { pendingId: string; name: string; cli_line: string }[];
  } | null;
  /** Engine ``awaiting_inbox_review`` (optional persisted gate). */
  inboxReviewBarrier?: {
    runId: string;
    watches: unknown[];
  } | null;
  approvalDecisions: Record<string, boolean | null>;
};

export type PlanClarificationQuestion = {
  id: string;
  prompt: string;
  options: { id: string; label: string }[];
  allow_multiple: boolean;
};

export type AgentConversationPlanV1 = {
  phase: "clarifying" | "generating" | "ready" | "executing" | "done";
  text: string;
  runId: string | null;
  clarificationBarrier?: {
    runId: string;
    clarificationId: string;
    questions: PlanClarificationQuestion[];
  } | null;
  /** Submitted clarification answers (for Answer card); optional for older snapshots. */
  clarificationSummary?: { prompt: string; selectedLabels: string[] }[];
  planTodoDoneIndices?: number[];
};

export type AgentConversationStateV1 = {
  version: 1;
  thread: unknown[];
  mutationOutcomes: Record<string, boolean>;
  draft?: AgentConversationDraftV1;
  plan?: AgentConversationPlanV1;
};
