import { describe, expect, it } from "vitest";
import { reasoningPhaseTickingLive } from "./assistantStreamSegments";

describe("reasoningPhaseTickingLive", () => {
  it("is true with an empty content tail (segment_start content before first reply token)", () => {
    const merged = [
      { kind: "reasoning" as const, text: "still thinking…" },
      { kind: "content" as const, text: "" },
    ];
    expect(reasoningPhaseTickingLive(merged, 0, 0, true)).toBe(true);
  });

  it("is false once the content segment has text (reply phase — timer must stop)", () => {
    const merged = [
      { kind: "reasoning" as const, text: "done" },
      { kind: "content" as const, text: "Hi" },
    ];
    expect(reasoningPhaseTickingLive(merged, 0, 0, true)).toBe(false);
  });

  it("is false when the assistant row is no longer streaming", () => {
    const merged = [
      { kind: "reasoning" as const, text: "done" },
      { kind: "content" as const, text: "" },
    ];
    expect(reasoningPhaseTickingLive(merged, 0, 0, false)).toBe(false);
  });

  it("is false for a non-last-reasoning segment", () => {
    const merged = [
      { kind: "reasoning" as const, text: "a" },
      { kind: "reasoning" as const, text: "b" },
    ];
    expect(reasoningPhaseTickingLive(merged, 0, 1, true)).toBe(false);
  });
});
