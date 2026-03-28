import { describe, expect, it } from "vitest";
import {
  computeLiveLabel,
  discoverPhaseToLabel,
  isLiveStreamLabel,
  isPlanCardLabel,
  isQuestionnaireLabel,
  settleLiveLabel,
} from "./planDiscoverStatusLabel";

describe("computeLiveLabel", () => {
  const base = {
    agentMode: "plan" as const,
    planBuiltinLane: null,
  };

  it("returns null when not plan mode", () => {
    expect(
      computeLiveLabel({
        ...base,
        agentMode: "instant",
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe(null);
  });

  it("maps discover phases", () => {
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
      }),
    ).toBe("Exploring");
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe("Generating questions");
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: null,
      }),
    ).toBe("Preparing plan");
  });

  it("shows settled \u201cGenerated questions\u201d while clarification questionnaire is on screen", () => {
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: "clarifying",
      }),
    ).toBe("Generated questions");
  });

  it("uses generating phase for post-clarification plan wait", () => {
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: "generating",
      }),
    ).toBe("Preparing plan");
  });

  it("falls back to builtin lane when discover phase missing", () => {
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "plan",
      }),
    ).toBe("Preparing plan");
  });

  it("builtin clarification lane wins over discover explore (server can lag)", () => {
    expect(
      computeLiveLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
  });
});

describe("settleLiveLabel", () => {
  it("maps live strings to past tense", () => {
    expect(settleLiveLabel("Exploring")).toBe("Explored");
    expect(settleLiveLabel("Generating questions")).toBe(
      "Generated questions",
    );
    expect(settleLiveLabel("Preparing plan")).toBe("Prepared plan");
  });

  it("passes through unknown labels", () => {
    expect(settleLiveLabel("Thinking")).toBe("Thinking");
  });
});

describe("discoverPhaseToLabel", () => {
  it("matches discover segment strings", () => {
    expect(discoverPhaseToLabel("explore")).toBe("Exploring");
    expect(discoverPhaseToLabel("clarify")).toBe("Generating questions");
    expect(discoverPhaseToLabel("propose")).toBe("Preparing plan");
    expect(discoverPhaseToLabel(null)).toBe(null);
  });
});

describe("label classification", () => {
  it("classifies questionnaire vs plan card vs live stream labels", () => {
    expect(isQuestionnaireLabel("Generating questions")).toBe(true);
    expect(isQuestionnaireLabel("Generated questions")).toBe(true);
    expect(isQuestionnaireLabel("Preparing plan")).toBe(false);

    expect(isPlanCardLabel("Preparing plan")).toBe(true);
    expect(isPlanCardLabel("Prepared plan")).toBe(true);
    expect(isPlanCardLabel("Exploring")).toBe(false);

    expect(isLiveStreamLabel("Exploring")).toBe(true);
    expect(isLiveStreamLabel("Explored")).toBe(true);
    expect(isLiveStreamLabel("Generating questions")).toBe(false);
  });
});
