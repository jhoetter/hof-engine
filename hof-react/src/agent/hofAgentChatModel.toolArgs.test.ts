import { describe, expect, it } from "vitest";
import { toolArgumentsAreEffectivelyEmpty } from "./hofAgentChatModel";

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
