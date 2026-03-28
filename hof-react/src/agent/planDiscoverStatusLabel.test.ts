import { describe, expect, it } from "vitest";
import {
  computePlanDiscoverLiveLabel,
  computePlanDiscoverStatusLabel,
  discoverPhaseToEagerLabel,
  isLiveStreamPlanDiscoverStatusLabel,
  isPlanCardPlanDiscoverStatusLabel,
  isQuestionnairePlanDiscoverStatusLabel,
  resolvePlanDiscoverStatusDisplayLabel,
  settlePlanDiscoverLiveLabel,
  shouldSuppressPlanDiscoverStampedLabel,
} from "./planDiscoverStatusLabel";

describe("computePlanDiscoverLiveLabel", () => {
  const base = {
    agentMode: "plan" as const,
    planBuiltinLane: null,
  };

  it("returns null when not plan mode", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        agentMode: "instant",
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe(null);
  });

  it("maps discover phases", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
      }),
    ).toBe("Exploring");
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe("Generating questions");
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: null,
      }),
    ).toBe("Preparing plan");
  });

  it("shows settled “Generated questions” while clarification questionnaire is on screen", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: "clarifying",
      }),
    ).toBe("Generated questions");
  });

  it("uses generating phase for post-clarification plan wait", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: "generating",
      }),
    ).toBe("Preparing plan");
  });

  it("falls back to builtin lane when discover phase missing", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "plan",
      }),
    ).toBe("Preparing plan");
  });

  it("builtin clarification lane wins over discover explore (server can lag)", () => {
    expect(
      computePlanDiscoverLiveLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
  });
});

describe("computePlanDiscoverStatusLabel (legacy busy gate)", () => {
  const base = {
    busy: true,
    agentMode: "plan" as const,
    planBuiltinLane: null,
  };

  it("returns null when not busy or not plan mode", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        busy: false,
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe(null);
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        agentMode: "instant",
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe(null);
  });

  it("delegates to live label when busy", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
      }),
    ).toBe("Exploring");
  });
});

describe("resolvePlanDiscoverStatusDisplayLabel", () => {
  const input = (
    busy: boolean,
    overrides: Partial<{
      agentMode: "instant" | "plan";
      discoverStreamPhase: "explore" | "clarify" | "propose" | null;
      planPhase:
        | null
        | "generating"
        | "clarifying"
        | "ready"
        | "executing"
        | "done";
      planBuiltinLane: "clarification" | "plan" | null;
    }> = {},
  ): import("./planDiscoverStatusLabel").PlanDiscoverStatusInput => ({
    busy,
    agentMode: "plan",
    discoverStreamPhase: "explore",
    planPhase: null,
    planBuiltinLane: null,
    ...overrides,
  });

  it("returns null when not plan mode", () => {
    expect(
      resolvePlanDiscoverStatusDisplayLabel(
        input(true, { agentMode: "instant" }),
        "Generated questions",
      ),
    ).toBe(null);
  });

  it("uses live label when busy", () => {
    expect(
      resolvePlanDiscoverStatusDisplayLabel(input(true), "Prepared plan"),
    ).toBe("Exploring");
  });

  it("uses persisted when not busy", () => {
    expect(
      resolvePlanDiscoverStatusDisplayLabel(input(false), "Generated questions"),
    ).toBe("Generated questions");
  });

  it("returns null when idle and no persisted label", () => {
    expect(resolvePlanDiscoverStatusDisplayLabel(input(false), null)).toBe(null);
  });
});

describe("settlePlanDiscoverLiveLabel", () => {
  it("maps live strings to past tense", () => {
    expect(settlePlanDiscoverLiveLabel("Exploring")).toBe("Explored");
    expect(settlePlanDiscoverLiveLabel("Generating questions")).toBe(
      "Generated questions",
    );
    expect(settlePlanDiscoverLiveLabel("Preparing plan")).toBe("Prepared plan");
  });

  it("passes through unknown labels", () => {
    expect(settlePlanDiscoverLiveLabel("Thinking")).toBe("Thinking");
  });
});

describe("discoverPhaseToEagerLabel", () => {
  it("matches discover segment strings", () => {
    expect(discoverPhaseToEagerLabel("explore")).toBe("Exploring");
    expect(discoverPhaseToEagerLabel("clarify")).toBe("Generating questions");
    expect(discoverPhaseToEagerLabel("propose")).toBe("Preparing plan");
    expect(discoverPhaseToEagerLabel(null)).toBe(null);
  });
});

describe("shouldSuppressPlanDiscoverStampedLabel", () => {
  it("suppresses questionnaire labels when the questionnaire card is visible", () => {
    expect(
      shouldSuppressPlanDiscoverStampedLabel(
        "Generated questions",
        true,
        false,
      ),
    ).toBe(true);
    expect(
      shouldSuppressPlanDiscoverStampedLabel(
        "Generating questions",
        true,
        false,
      ),
    ).toBe(true);
    expect(
      shouldSuppressPlanDiscoverStampedLabel(
        "Generated questions",
        false,
        false,
      ),
    ).toBe(false);
  });

  it("suppresses plan card labels when the plan card is visible", () => {
    expect(
      shouldSuppressPlanDiscoverStampedLabel("Prepared plan", false, true),
    ).toBe(true);
    expect(
      shouldSuppressPlanDiscoverStampedLabel("Preparing plan", false, true),
    ).toBe(true);
    expect(
      shouldSuppressPlanDiscoverStampedLabel("Prepared plan", false, false),
    ).toBe(false);
  });

  it("returns false for empty label", () => {
    expect(
      shouldSuppressPlanDiscoverStampedLabel(undefined, true, true),
    ).toBe(false);
    expect(shouldSuppressPlanDiscoverStampedLabel("  ", true, true)).toBe(
      false,
    );
  });
});

describe("plan-discover label classification", () => {
  it("classifies questionnaire vs plan card vs live stream labels", () => {
    expect(isQuestionnairePlanDiscoverStatusLabel("Generating questions")).toBe(
      true,
    );
    expect(isQuestionnairePlanDiscoverStatusLabel("Generated questions")).toBe(
      true,
    );
    expect(isQuestionnairePlanDiscoverStatusLabel("Preparing plan")).toBe(false);

    expect(isPlanCardPlanDiscoverStatusLabel("Preparing plan")).toBe(true);
    expect(isPlanCardPlanDiscoverStatusLabel("Prepared plan")).toBe(true);
    expect(isPlanCardPlanDiscoverStatusLabel("Exploring")).toBe(false);

    expect(isLiveStreamPlanDiscoverStatusLabel("Exploring")).toBe(true);
    expect(isLiveStreamPlanDiscoverStatusLabel("Explored")).toBe(true);
    expect(isLiveStreamPlanDiscoverStatusLabel("Generating questions")).toBe(
      false,
    );
  });
});
