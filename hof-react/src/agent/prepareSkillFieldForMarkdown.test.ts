import { describe, expect, it } from "vitest";
import {
  cleandoc,
  isGuidanceRedundantInDescription,
  prepareSkillMarkdownField,
  stripGuidanceParagraphsForStructuredSections,
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

describe("prepareSkillMarkdownField polish", () => {
  it("fixes space before period after closing paren (spreadsheet #)", () => {
    const raw = "Pass either `id` or `display_seq` (spreadsheet # ) . Read-only.";
    expect(prepareSkillMarkdownField(raw)).toBe(
      "Pass either `id` or `display_seq` (spreadsheet #). Read-only.",
    );
  });

  it("rewrites mutation confirms-in-UI phrasing for end users", () => {
    expect(
      prepareSkillMarkdownField(
        "Bulk insert (mutation — confirms in assistant UI). Done.",
      ),
    ).toContain("requires your approval in the app");
    expect(prepareSkillMarkdownField("Bulk insert (mutation — confirms in assistant UI).")).not.toMatch(
      /\(mutation/i,
    );
  });

  it("rewrites Mutation (confirms in UI) parenthetical", () => {
    const out = prepareSkillMarkdownField(
      "New row. Mutation (confirms in UI). More text.",
    );
    expect(out).toContain("requires your approval in the app");
    expect(out).not.toMatch(/Mutation\s*\(/i);
  });

  it("normalizes slash between inline code spans to a comma list", () => {
    expect(prepareSkillMarkdownField("Use `a` / `b` then `c`.")).toBe("Use `a`, `b` then `c`.");
  });

  it("collapses extra blank lines and trims inline code", () => {
    const raw = "One.\n\n\n\nTwo.  `  x  ` end.";
    const out = prepareSkillMarkdownField(raw);
    expect(out).toContain("`x`");
    expect(out).toContain("One.\n\nTwo.");
    expect(out).not.toMatch(/\n\n\n/);
  });
});

describe("stripGuidanceParagraphsForStructuredSections", () => {
  it("removes When to use paragraph when structured section is shown", () => {
    const prepared = prepareSkillMarkdownField(
      "Intro line.\n\n**When to use:** duplicate heading body.\n\nFooter.",
    );
    const out = stripGuidanceParagraphsForStructuredSections(prepared, {
      showStructuredWhen: true,
      showStructuredWhenNot: false,
    });
    expect(out).toContain("Intro line.");
    expect(out).toContain("Footer.");
    expect(out).not.toMatch(/When\s+to\s+use/i);
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
