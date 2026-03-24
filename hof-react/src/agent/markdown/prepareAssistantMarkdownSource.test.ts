import { describe, expect, it } from "vitest";
import { prepareAssistantMarkdownSource } from "./prepareAssistantMarkdownSource";

describe("prepareAssistantMarkdownSource", () => {
  it("neutralizes consecutive pipe rows without a delimiter row", () => {
    const src = ["| MacBook |", "| 2024: € |"].join("\n");
    const out = prepareAssistantMarkdownSource(src);
    expect(out).not.toMatch(/^\| MacBook/m);
    expect(out).toContain("&#124;");
    expect(out).toContain("MacBook");
  });

  it("leaves real GFM tables intact (header + delimiter)", () => {
    const src = ["| A | B |", "| --- | --- |", "| 1 | 2 |"].join("\n");
    expect(prepareAssistantMarkdownSource(src)).toBe(src);
  });

  it("does not modify content inside fenced code blocks", () => {
    const inner = ["| a |", "| b |"].join("\n");
    const src = ["```text", inner, "```"].join("\n");
    expect(prepareAssistantMarkdownSource(src)).toBe(src);
  });

  it("still neutralizes pipe rows outside fences when a fence is present", () => {
    const src = [
      "| x |",
      "| y |",
      "",
      "```",
      "| keep |",
      "```",
      "| z |",
      "| w |",
    ].join("\n");
    const out = prepareAssistantMarkdownSource(src);
    expect(out).toContain("&#124;");
    expect(out).toMatch(/\|\s*keep\s*\|/);
  });
});
