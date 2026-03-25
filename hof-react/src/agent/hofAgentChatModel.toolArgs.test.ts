import { describe, expect, it } from "vitest";
import {
  toolArgumentsAreEffectivelyEmpty,
  toolCallCliLine,
} from "./hofAgentChatModel";

describe("toolArgumentsAreEffectivelyEmpty", () => {
  it("treats missing and whitespace as empty", () => {
    expect(toolArgumentsAreEffectivelyEmpty(undefined)).toBe(true);
    expect(toolArgumentsAreEffectivelyEmpty(null)).toBe(true);
    expect(toolArgumentsAreEffectivelyEmpty("")).toBe(true);
    expect(toolArgumentsAreEffectivelyEmpty("  \n  ")).toBe(true);
  });

  it("treats {} and [] as empty", () => {
    expect(toolArgumentsAreEffectivelyEmpty("{}")).toBe(true);
    expect(toolArgumentsAreEffectivelyEmpty("[]")).toBe(true);
    expect(toolArgumentsAreEffectivelyEmpty("  {}  ")).toBe(true);
  });

  it("treats non-empty JSON as non-empty", () => {
    expect(toolArgumentsAreEffectivelyEmpty('{"page":1}')).toBe(false);
    expect(toolArgumentsAreEffectivelyEmpty("[1]")).toBe(false);
  });

  it("treats invalid JSON as non-empty", () => {
    expect(toolArgumentsAreEffectivelyEmpty("not json")).toBe(false);
  });
});

describe("toolCallCliLine", () => {
  it("replaces legacy POST /api/functions/… lines with hof fn + arguments", () => {
    expect(
      toolCallCliLine({
        kind: "tool_call",
        id: "c1",
        name: "bulk_create_expenses",
        arguments: '{"rows":[]}',
        cli_line: 'POST /api/functions/bulk_create_expenses {"rows":[]}',
      }),
    ).toBe('hof fn bulk_create_expenses {"rows":[]}');
  });

  it("keeps server hof fn lines when present", () => {
    expect(
      toolCallCliLine({
        kind: "tool_call",
        id: "c1",
        name: "list_expenses",
        arguments: '{"page":1}',
        cli_line: "hof fn list_expenses --page 1",
      }),
    ).toBe("hof fn list_expenses --page 1");
  });
});
