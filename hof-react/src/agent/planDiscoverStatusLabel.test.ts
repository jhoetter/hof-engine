import { describe, expect, it } from "vitest";
import {
  computePlanDiscoverStatusLabel,
  discoverPhaseToEagerLabel,
} from "./planDiscoverStatusLabel";

describe("computePlanDiscoverStatusLabel", () => {
  const base = {
    busy: true,
    agentMode: "plan" as const,
    planBuiltinLane: null as const,
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

  it("maps discover phases", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
      }),
    ).toBe("Exploring");
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: null,
      }),
    ).toBe("Generating questions");
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: null,
      }),
    ).toBe("Preparing plan");
  });

  it("hides label when clarification questionnaire is on screen", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "clarify",
        planPhase: "clarifying",
      }),
    ).toBe(null);
  });

  it("uses generating phase for post-clarification plan wait", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "propose",
        planPhase: "generating",
      }),
    ).toBe("Preparing plan");
  });

  it("falls back to builtin lane when discover phase missing", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: null,
        planPhase: null,
        planBuiltinLane: "plan",
      }),
    ).toBe("Preparing plan");
  });

  it("builtin clarification lane wins over discover explore (server can lag)", () => {
    expect(
      computePlanDiscoverStatusLabel({
        ...base,
        discoverStreamPhase: "explore",
        planPhase: null,
        planBuiltinLane: "clarification",
      }),
    ).toBe("Generating questions");
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
