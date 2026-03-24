import { describe, expect, it } from "vitest";
import {
  appendAssistantStreamSegmentChunk,
  mergeAdjacentContentSegments,
  mergeAdjacentReasoningSegments,
  normalizeAssistantStreamSegments,
} from "./assistantStreamSegments";

describe("appendAssistantStreamSegmentChunk", () => {
  it("starts a new segment when none exist", () => {
    expect(appendAssistantStreamSegmentChunk(undefined, "reasoning", "a")).toEqual([
      { kind: "reasoning", text: "a" },
    ]);
  });

  it("appends to the tail when kind matches", () => {
    const s = appendAssistantStreamSegmentChunk(
      [{ kind: "reasoning", text: "a" }],
      "reasoning",
      "b",
    );
    expect(s).toEqual([{ kind: "reasoning", text: "ab" }]);
  });

  it("opens a new segment when kind changes", () => {
    const s = appendAssistantStreamSegmentChunk(
      [{ kind: "reasoning", text: "x" }],
      "content",
      "y",
    );
    expect(s).toEqual([
      { kind: "reasoning", text: "x" },
      { kind: "content", text: "y" },
    ]);
  });
});

describe("mergeAdjacentReasoningSegments", () => {
  it("merges consecutive reasoning segments", () => {
    expect(
      mergeAdjacentReasoningSegments([
        { kind: "reasoning", text: "a" },
        { kind: "reasoning", text: "b" },
      ]),
    ).toEqual([{ kind: "reasoning", text: "a\n\nb" }]);
  });
});

describe("mergeAdjacentContentSegments", () => {
  it("merges consecutive content segments", () => {
    expect(
      mergeAdjacentContentSegments([
        { kind: "content", text: "hello" },
        { kind: "content", text: "world" },
      ]),
    ).toEqual([{ kind: "content", text: "hello\n\nworld" }]);
  });
});

describe("normalizeAssistantStreamSegments", () => {
  it("returns empty array unchanged", () => {
    expect(normalizeAssistantStreamSegments([])).toEqual([]);
  });

  it("strips trailing empty content shells", () => {
    expect(
      normalizeAssistantStreamSegments([
        { kind: "content", text: "done" },
        { kind: "content", text: "   " },
      ]),
    ).toEqual([{ kind: "content", text: "done" }]);
  });

  it("keeps reasoning even when identical to the following reply (separate thinking vs answer rows)", () => {
    const dup = "The total for Q4 is 19,200 EUR before tax.";
    const out = normalizeAssistantStreamSegments([
      { kind: "reasoning", text: dup },
      { kind: "content", text: dup },
    ]);
    expect(out.length).toBe(2);
    expect(out[0]).toEqual({ kind: "reasoning", text: dup });
    expect(out[1]).toEqual({ kind: "content", text: dup });
  });

  it("keeps substantive reasoning that is not a near-duplicate of the reply", () => {
    const reasoning =
      "The user asked for Q4 totals. I will call list_expenses with date filters.";
    const content = "Here are your Q4 expenses.";
    const out = normalizeAssistantStreamSegments([
      { kind: "reasoning", text: reasoning },
      { kind: "content", text: content },
    ]);
    expect(out.length).toBe(2);
    expect(out[0]).toEqual({ kind: "reasoning", text: reasoning });
    expect(out[1]).toEqual({ kind: "content", text: content });
  });

  it("keeps empty reasoning before non-empty content (structural thinking row)", () => {
    const content = "Here are your expenses.";
    const out = normalizeAssistantStreamSegments([
      { kind: "reasoning", text: "" },
      { kind: "content", text: content },
    ]);
    expect(out).toEqual([
      { kind: "reasoning", text: "" },
      { kind: "content", text: content },
    ]);
  });

  it("drops trailing empty reasoning with no following content", () => {
    expect(
      normalizeAssistantStreamSegments([
        { kind: "content", text: "done" },
        { kind: "reasoning", text: "" },
      ]),
    ).toEqual([{ kind: "content", text: "done" }]);
  });
});
