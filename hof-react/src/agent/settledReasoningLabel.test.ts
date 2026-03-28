import { describe, expect, it } from "vitest";
import { settledReasoningLabel } from "./HofAgentChatBlocks";

describe("settledReasoningLabel", () => {
  it("maps plan-discover streaming labels to past tense", () => {
    expect(settledReasoningLabel("Exploring")).toBe("Explored");
    expect(settledReasoningLabel("Generating questions")).toBe(
      "Generated questions",
    );
    expect(settledReasoningLabel("Preparing plan")).toBe("Prepared plan");
  });

  it("passes through unknown labels", () => {
    expect(settledReasoningLabel("Custom")).toBe("Custom");
  });
});
