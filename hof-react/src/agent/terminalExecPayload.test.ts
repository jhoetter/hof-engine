import { describe, expect, it } from "vitest";
import { parseTerminalExecPayload } from "./terminalExecPayload";

describe("parseTerminalExecPayload", () => {
  it("parses standard shape", () => {
    expect(
      parseTerminalExecPayload({
        exit_code: 0,
        output: '{"result":{"rows":[]}}',
      }),
    ).toEqual({ exit_code: 0, output: '{"result":{"rows":[]}}' });
  });

  it("parses JSON string payload", () => {
    const raw = '{"exit_code":0,"output":"hello"}';
    expect(parseTerminalExecPayload(raw)).toEqual({
      exit_code: 0,
      output: "hello",
    });
  });

  it("coerces string exit_code", () => {
    expect(
      parseTerminalExecPayload({ exit_code: "0", output: "" }),
    ).toEqual({ exit_code: 0, output: "" });
  });

  it("unwraps result wrapper when top has no exit_code", () => {
    expect(
      parseTerminalExecPayload({
        result: { exit_code: 0, output: "x" },
      }),
    ).toEqual({ exit_code: 0, output: "x" });
  });

  it("unwraps result when it is a JSON string (proxy / HTTP wrappers)", () => {
    const inner = JSON.stringify({
      exit_code: 0,
      output: JSON.stringify({ result: { rows: [] } }),
    });
    expect(
      parseTerminalExecPayload({
        result: inner,
        duration_ms: 0,
      }),
    ).toEqual({
      exit_code: 0,
      output: JSON.stringify({ result: { rows: [] } }),
    });
  });

  it("unwraps data wrapper", () => {
    expect(
      parseTerminalExecPayload({
        data: {
          exit_code: 0,
          output: '{"result":{"rows":[]}}',
        },
      }),
    ).toEqual({ exit_code: 0, output: '{"result":{"rows":[]}}' });
  });

  it("does not unwrap when top has exit_code", () => {
    expect(
      parseTerminalExecPayload({
        exit_code: 1,
        output: "err",
        result: { rows: [] },
      }),
    ).toEqual({ exit_code: 1, output: "err" });
  });

  it("returns null for list_expenses-style payloads", () => {
    expect(parseTerminalExecPayload({ rows: [], total: 0 })).toBeNull();
  });
});
