import { describe, expect, it } from "vitest";
import {
  cleandoc,
  isGuidanceRedundantInDescription,
  prepareSkillMarkdownField,
} from "./prepareSkillFieldForMarkdown";

describe("cleandoc", () => {
  it("removes shared leading indent from docstring-style lines", () => {
    const raw = `
    Line one.
      Line two indented once more.
    Line three.
    `;
    const out = cleandoc(raw);
    expect(out).toContain("Line one.");
    expect(out).not.toMatch(/^\s{4}Line one/m);
    expect(out).toContain("Line two indented once more.");
  });
});

describe("isGuidanceRedundantInDescription", () => {
  it("returns false for short snippets", () => {
    expect(
      isGuidanceRedundantInDescription("long body here", "short", 24),
    ).toBe(false);
  });

  it("returns true when description already contains the guidance", () => {
    const guidance =
      "Use this when the user wants to bulk import many rows in one request.";
    const desc = `Does a thing.\n\nWhen to use: ${guidance}`;
    expect(
      isGuidanceRedundantInDescription(
        prepareSkillMarkdownField(desc),
        prepareSkillMarkdownField(guidance),
      ),
    ).toBe(true);
  });
});
