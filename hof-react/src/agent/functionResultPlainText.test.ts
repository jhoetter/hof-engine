import { describe, expect, it } from "vitest";
import { formatFunctionResultPlainText } from "./functionResultPlainText";

describe("formatFunctionResultPlainText", () => {
  it("formats rows + total with column cap notice", () => {
    const cols = Array.from({ length: 10 }, (_, i) => `c${i}`);
    const row: Record<string, unknown> = {};
    for (const c of cols) {
      row[c] = 1;
    }
    const text = formatFunctionResultPlainText({
      rows: [row],
      total: 99,
    });
    expect(text).toContain("Showing 8 of 10 columns");
    expect(text).toContain("total = 99");
    expect(text).toMatch(/c0\s+c1/);
  });

  it("truncates row list with notice", () => {
    const rows = Array.from({ length: 101 }, (_, i) => ({ id: i }));
    const text = formatFunctionResultPlainText({ rows, total: 1000 });
    expect(text).toContain("… 1 more rows not shown");
    expect(text).toContain("total = 1000");
  });

  it("formats flat dict as key / value lines", () => {
    const text = formatFunctionResultPlainText({ b: 2, a: 1 });
    expect(text).toBe("a    1\nb    2");
  });

  it("formats list of dicts without total", () => {
    const text = formatFunctionResultPlainText([{ x: "a" }, { x: "b" }]);
    expect(text).toContain("x");
    expect(text).toContain("a");
    expect(text).toContain("b");
  });

  it("empty rows object", () => {
    expect(
      formatFunctionResultPlainText({ rows: [], total: 0 }),
    ).toContain("(empty rows)");
  });
});
