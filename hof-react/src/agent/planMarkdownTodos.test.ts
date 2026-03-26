import { describe, expect, it } from "vitest";
import {
  parseStructuredPlan,
  preferPlanTaskListBody,
  sliceMarkdownFromFirstTaskListLine,
} from "./planMarkdownTodos";

describe("sliceMarkdownFromFirstTaskListLine", () => {
  it("returns empty when no task line", () => {
    expect(sliceMarkdownFromFirstTaskListLine("Hello world")).toBe("");
    expect(
      sliceMarkdownFromFirstTaskListLine(
        "Ich werde zunächst alle relevanten Daten laden.",
      ),
    ).toBe("");
  });

  it("strips prose before first checklist", () => {
    const raw =
      "Here is the plan.\n\n- [ ] First\n- [ ] Second";
    expect(sliceMarkdownFromFirstTaskListLine(raw)).toBe(
      "- [ ] First\n- [ ] Second",
    );
  });

  it("handles bullet variants", () => {
    expect(sliceMarkdownFromFirstTaskListLine("* [ ] One")).toBe("* [ ] One");
  });
});

describe("preferPlanTaskListBody", () => {
  it("falls back to full text when no task line", () => {
    expect(preferPlanTaskListBody("  only prose  ")).toBe("only prose");
  });

  it("uses slice when checklist present", () => {
    expect(preferPlanTaskListBody("Intro\n- [ ] A")).toBe("- [ ] A");
  });

  it("keeps full structured plan when markdown heading present", () => {
    const md = "# Title\n\nDesc.\n\n- [ ] One";
    expect(preferPlanTaskListBody(md)).toBe(md);
  });
});

describe("parseStructuredPlan", () => {
  it("parses heading, description, and todos", () => {
    const md =
      "# CRM direction\n\nExtend the admin portal.\n\n- [ ] Step one\n- [ ] Step two";
    const p = parseStructuredPlan(md);
    expect(p.title).toBe("CRM direction");
    expect(p.description).toBe("Extend the admin portal.");
    expect(p.todos).toHaveLength(2);
    expect(p.todos[0]!.label).toBe("Step one");
  });
});
