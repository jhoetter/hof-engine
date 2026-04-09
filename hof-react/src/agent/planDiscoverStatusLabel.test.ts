import i18n from "i18next";
import { beforeAll, describe, expect, it } from "vitest";
import en from "../../locales/en/hofEngine.json";
import {
  computeLiveLabel,
  discoverPhaseToLabel,
  isLiveStreamLabel,
  isPlanCardLabel,
  isQuestionnaireLabel,
  settleLiveLabel,
} from "./planDiscoverStatusLabel";

let t: ReturnType<typeof i18n.getFixedT>;

beforeAll(async () => {
  await i18n.init({
    lng: "en",
    fallbackLng: "en",
    ns: ["hofEngine"],
    defaultNS: "hofEngine",
    resources: { en: { hofEngine: en } },
    interpolation: { escapeValue: false },
  });
  t = i18n.getFixedT("en", "hofEngine");
});

describe("computeLiveLabel", () => {
  const base = {
    agentMode: "plan" as const,
    planBuiltinLane: null,
  };

  it("returns null when not plan mode", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          agentMode: "instant",
          discoverStreamPhase: "clarify",
          planPhase: null,
        },
        t,
      ),
    ).toBe(null);
  });

  it("maps discover phases", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "explore",
          planPhase: null,
        },
        t,
      ),
    ).toBe("Exploring");
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "clarify",
          planPhase: null,
        },
        t,
      ),
    ).toBe("Generating questions");
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "propose",
          planPhase: null,
        },
        t,
      ),
    ).toBe("Preparing plan");
  });

  it("shows settled “Generated questions” while clarification questionnaire is on screen", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "clarify",
          planPhase: "clarifying",
        },
        t,
      ),
    ).toBe("Generated questions");
  });

  it("uses generating phase for post-clarification plan wait", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "propose",
          planPhase: "generating",
        },
        t,
      ),
    ).toBe("Preparing plan");
  });

  it("falls back to builtin lane when discover phase missing", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: null,
          planPhase: null,
          planBuiltinLane: "clarification",
        },
        t,
      ),
    ).toBe("Generating questions");
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: null,
          planPhase: null,
          planBuiltinLane: "plan",
        },
        t,
      ),
    ).toBe("Preparing plan");
  });

  it("builtin clarification lane wins over discover explore (server can lag)", () => {
    expect(
      computeLiveLabel(
        {
          ...base,
          discoverStreamPhase: "explore",
          planPhase: null,
          planBuiltinLane: "clarification",
        },
        t,
      ),
    ).toBe("Generating questions");
  });
});

describe("settleLiveLabel", () => {
  it("maps live strings to past tense", () => {
    expect(settleLiveLabel("Exploring", t)).toBe("Explored");
    expect(settleLiveLabel("Generating questions", t)).toBe(
      "Generated questions",
    );
    expect(settleLiveLabel("Preparing plan", t)).toBe("Prepared plan");
  });

  it("passes through unknown labels", () => {
    expect(settleLiveLabel("Thinking", t)).toBe("Thinking");
  });
});

describe("discoverPhaseToLabel", () => {
  it("matches discover segment strings", () => {
    expect(discoverPhaseToLabel("explore", t)).toBe("Exploring");
    expect(discoverPhaseToLabel("clarify", t)).toBe("Generating questions");
    expect(discoverPhaseToLabel("propose", t)).toBe("Preparing plan");
    expect(discoverPhaseToLabel(null, t)).toBe(null);
  });
});

describe("label classification", () => {
  it("classifies questionnaire vs plan card vs live stream labels", () => {
    expect(isQuestionnaireLabel("Generating questions", t)).toBe(true);
    expect(isQuestionnaireLabel("Generated questions", t)).toBe(true);
    expect(isQuestionnaireLabel("Preparing plan", t)).toBe(false);

    expect(isPlanCardLabel("Preparing plan", t)).toBe(true);
    expect(isPlanCardLabel("Prepared plan", t)).toBe(true);
    expect(isPlanCardLabel("Exploring", t)).toBe(false);

    expect(isLiveStreamLabel("Exploring", t)).toBe(true);
    expect(isLiveStreamLabel("Explored", t)).toBe(true);
    expect(isLiveStreamLabel("Generating questions", t)).toBe(false);
  });
});
