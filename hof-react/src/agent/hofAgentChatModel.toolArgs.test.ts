import { describe, expect, it } from "vitest";
import {
  extractFunctionNameFromShellCommand,
  pseudoHofFnCliFromShellCommand,
  toolArgumentsAreEffectivelyEmpty,
  toolCallCliLine,
  toolCallRowTitle,
  underlyingFunctionFromTerminalExecArguments,
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

  it("normalizes terminal exec curl to hof fn underlying name", () => {
    const args = JSON.stringify({
      command:
        'curl -sS -X POST "$API_BASE_URL/api/functions/create_expense" -H "Content-Type: application/json" -d "{}"',
    });
    expect(
      toolCallCliLine({
        kind: "tool_call",
        id: "t1",
        name: "hof_builtin_terminal_exec",
        arguments: args,
        cli_line: "hof fn hof_builtin_terminal_exec --command 'curl …'",
      }),
    ).toBe("hof fn create_expense");
  });

  it("uses underlying name when cli_line is absent", () => {
    const args = JSON.stringify({
      command: "hof fn list_expenses --page 1",
    });
    expect(
      toolCallCliLine({
        kind: "tool_call",
        id: "t2",
        name: "hof_builtin_terminal_exec",
        arguments: args,
        cli_line: "",
      }),
    ).toBe("hof fn list_expenses");
  });

  it("converts hof fn JSON body to flag-style pseudo-CLI (no duplicate footer)", () => {
    const cmd = `hof fn create_expense '{"description":"Coffee","amount":12.5,"date":"2026-03-29","category":"Food"}'`;
    const args = JSON.stringify({ command: cmd });
    const line = toolCallCliLine({
      kind: "tool_call",
      id: "t4",
      name: "hof_builtin_terminal_exec",
      arguments: args,
      cli_line: cmd,
    });
    expect(line).toContain("--description");
    expect(line).toContain("Coffee");
    expect(line).toContain("--amount");
    expect(line).not.toMatch(/'\{"description"/);
  });
});

describe("pseudoHofFnCliFromShellCommand", () => {
  it("returns flag line for flat JSON object", () => {
    const line = pseudoHofFnCliFromShellCommand(
      `hof fn list_expenses '{"search":"","page":1,"page_size":100}'`,
      500,
    );
    expect(line).toContain("hof fn list_expenses");
    expect(line).toContain("--page");
    expect(line).toContain("--page_size");
  });
});

describe("extractFunctionNameFromShellCommand", () => {
  it("parses hof fn name", () => {
    expect(extractFunctionNameFromShellCommand("hof fn list_expenses --page 2")).toBe(
      "list_expenses",
    );
  });

  it("parses api/functions path", () => {
    expect(
      extractFunctionNameFromShellCommand(
        'curl "$API_BASE_URL/api/functions/create_expense"',
      ),
    ).toBe("create_expense");
  });
});

describe("underlyingFunctionFromTerminalExecArguments", () => {
  it("reads command field from JSON", () => {
    expect(
      underlyingFunctionFromTerminalExecArguments(
        JSON.stringify({ command: "hof fn delete_expense --id 1" }),
      ),
    ).toBe("delete_expense");
  });
});

describe("toolCallRowTitle", () => {
  it("uses humanized underlying function for terminal exec", () => {
    const args = JSON.stringify({
      command: 'curl -X POST /api/functions/create_expense',
    });
    expect(
      toolCallRowTitle({
        name: "hof_builtin_terminal_exec",
        arguments: args,
      }),
    ).toBe("Create Expense");
  });
});
