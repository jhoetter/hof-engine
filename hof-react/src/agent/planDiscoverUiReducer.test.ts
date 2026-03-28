import { describe, expect, it } from "vitest";
import { computePlanDiscoverUiState } from "./planDiscoverUiReducer";

describe("computePlanDiscoverUiState", () => {
  it("instant: none when idle", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "instant",
        busy: false,
        displayLabel: null,
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 0,
      }),
    ).toEqual({ placement: "none", label: null, timerKind: null });
  });

  it("instant: above_live_stream + thinking_episode before first block", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "instant",
        busy: true,
        displayLabel: null,
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 0,
      }),
    ).toEqual({
      placement: "above_live_stream",
      label: null,
      timerKind: "thinking_episode",
    });
  });

  it("instant: none when busy but blocks exist", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "instant",
        busy: true,
        displayLabel: null,
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 1,
      }),
    ).toEqual({ placement: "none", label: null, timerKind: null });
  });

  it("plan: questionnaire label above questionnaire when card visible", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: "Generating questions",
        hasQuestionnaireCard: true,
        showPlanCard: false,
        liveBlocksLength: 0,
      }),
    ).toEqual({
      placement: "above_questionnaire",
      label: "Generating questions",
      timerKind: "clarification_generation",
    });
  });

  it("plan: questionnaire label above stream when no card yet", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: "Generating questions",
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 0,
        pendingQuestionnaireGeneration: false,
      }),
    ).toEqual({
      placement: "above_live_stream",
      label: null,
      timerKind: "thinking_episode",
    });
  });

  it("plan: pending clarification builtin uses questionnaire slot", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: "Generating questions",
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 3,
        pendingQuestionnaireGeneration: true,
      }),
    ).toEqual({
      placement: "above_questionnaire",
      label: null,
      timerKind: "clarification_generation",
    });
  });

  it("plan: plan label above plan card when visible", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: "Preparing plan",
        hasQuestionnaireCard: false,
        showPlanCard: true,
        liveBlocksLength: 0,
      }),
    ).toEqual({
      placement: "above_plan",
      label: "Preparing plan",
      timerKind: "plan_preparation",
    });
  });

  it("plan: live-stream discover label keeps label + thinking_episode", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: "Exploring",
        hasQuestionnaireCard: false,
        showPlanCard: false,
        liveBlocksLength: 0,
      }),
    ).toEqual({
      placement: "above_live_stream",
      label: "Exploring",
      timerKind: "thinking_episode",
    });
  });

  it("plan: none when busy with no label and blocks exist (execution)", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: null,
        hasQuestionnaireCard: false,
        showPlanCard: true,
        liveBlocksLength: 3,
      }),
    ).toEqual({ placement: "none", label: null, timerKind: null });
  });

  it("plan: above_live_stream when busy with no label and no blocks yet (pre-execution)", () => {
    expect(
      computePlanDiscoverUiState({
        agentMode: "plan",
        busy: true,
        displayLabel: null,
        hasQuestionnaireCard: false,
        showPlanCard: true,
        liveBlocksLength: 0,
      }),
    ).toEqual({
      placement: "above_live_stream",
      label: null,
      timerKind: "thinking_episode",
    });
  });
});
