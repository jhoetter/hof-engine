import { describe, expect, it } from "vitest";
import {
  normalizePlanTodoWireIndices,
  parseStructuredPlan,
  preferPlanTaskListBody,
  sliceMarkdownFromFirstTaskListLine,
  visiblePlanMarkdownPreview,
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

describe("visiblePlanMarkdownPreview", () => {
  it("returns empty until a heading or task line exists", () => {
    expect(visiblePlanMarkdownPreview("Perfekt! Ich erstelle nun einen Plan.")).toBe(
      "",
    );
    expect(visiblePlanMarkdownPreview("No structure yet ")).toBe("");
  });

  it("keeps from first markdown heading", () => {
    const raw =
      "Intro sentence.\n\n# Abschreibungsplan\n\n- [ ] One\n- [ ] Two";
    expect(visiblePlanMarkdownPreview(raw)).toBe(
      "# Abschreibungsplan\n\n- [ ] One\n- [ ] Two",
    );
  });

  it("falls back to first task line when there is no heading", () => {
    const raw = "Short intro\n\n- [ ] First\n- [ ] Second";
    expect(visiblePlanMarkdownPreview(raw)).toBe("- [ ] First\n- [ ] Second");
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

describe("normalizePlanTodoWireIndices", () => {
  it("maps 1..n (human steps) to 0..n-1 for a full set", () => {
    expect(normalizePlanTodoWireIndices([1, 2, 3, 4, 5], 5)).toEqual([
      0, 1, 2, 3, 4,
    ]);
  });

  it("maps consecutive 1..k prefix to 0..k-1 during streaming", () => {
    expect(normalizePlanTodoWireIndices([1, 2, 3], 5)).toEqual([0, 1, 2]);
  });

  it("keeps 0-based indices when 0 is present", () => {
    expect(normalizePlanTodoWireIndices([0, 1], 5)).toEqual([0, 1]);
  });

  it("maps a single out-of-range 1-based index (e.g. 5 for 5 items)", () => {
    expect(normalizePlanTodoWireIndices([5], 5)).toEqual([4]);
  });
});
