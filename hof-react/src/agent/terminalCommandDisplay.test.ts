import { describe, expect, it } from "vitest";
import {
  displayShellInvocationFromOpener,
  type ParsedTerminalCommand,
  parseTerminalCommandForDisplay,
} from "./terminalCommandDisplay";

/** Flatten how the assistant UI shows a heredoc (tests only). */
function uiHeredocDisplay(p: ParsedTerminalCommand): string {
  if (p.kind === "single") {
    return p.text;
  }
  const head = displayShellInvocationFromOpener(p.shellOpener);
  const parts: string[] = [];
  if (head.length > 0) {
    parts.push(head);
  }
  if (p.body.length > 0) {
    parts.push(p.body);
  }
  return parts.join("\n");
}

describe("displayShellInvocationFromOpener", () => {
  it("drops heredoc operator and quoted delimiter", () => {
    expect(displayShellInvocationFromOpener(`python3 << 'EOF'`)).toBe("python3");
  });

  it("drops <<- unquoted delimiter", () => {
    expect(displayShellInvocationFromOpener("sh <<-PY")).toBe("sh");
  });

  it("basename for lone absolute path", () => {
    expect(
      displayShellInvocationFromOpener(`/usr/bin/python3 << 'EOF'`),
    ).toBe("python3");
  });

  it("keeps multi-token invocation", () => {
    expect(displayShellInvocationFromOpener(`env python3 << 'EOF'`)).toBe(
      "env python3",
    );
  });
});

describe("parseTerminalCommandForDisplay", () => {
  it("treats non-heredoc as single", () => {
    expect(parseTerminalCommandForDisplay("echo hello")).toEqual({
      kind: "single",
      text: "echo hello",
    });
  });

  it("parses complete quoted heredoc", () => {
    const raw = `python3 << 'EOF'
import sys
print(1)
EOF`;
    expect(parseTerminalCommandForDisplay(raw)).toEqual({
      kind: "heredoc",
      shellOpener: `python3 << 'EOF'`,
      body: "import sys\nprint(1)",
      closingLine: "EOF",
    });
  });

  it("parses <<- stripped-tab opener", () => {
    const raw = `sh <<-PY
x=1
PY`;
    expect(parseTerminalCommandForDisplay(raw)).toEqual({
      kind: "heredoc",
      shellOpener: "sh <<-PY",
      body: "x=1",
      closingLine: "PY",
    });
  });

  it("parses incomplete heredoc without closing line", () => {
    const raw = `python3 << 'EOF'
still open`;
    expect(parseTerminalCommandForDisplay(raw)).toEqual({
      kind: "heredoc",
      shellOpener: `python3 << 'EOF'`,
      body: "still open",
      closingLine: undefined,
    });
  });

  it("parses opener-only heredoc", () => {
    expect(parseTerminalCommandForDisplay(`python3 << 'EOF'`)).toEqual({
      kind: "heredoc",
      shellOpener: `python3 << 'EOF'`,
      body: "",
      closingLine: undefined,
    });
  });

  it("preserves blank lines inside body", () => {
    const raw = `python3 << 'EOF'
line1

line2
EOF`;
    expect(parseTerminalCommandForDisplay(raw)).toEqual({
      kind: "heredoc",
      shellOpener: `python3 << 'EOF'`,
      body: "line1\n\nline2",
      closingLine: "EOF",
    });
  });
});

describe("ui heredoc display (test helper)", () => {
  it("shows interpreter + body without << or closing delimiter", () => {
    const raw = `python3 << 'EOF'
import sys
print(1)
EOF`;
    expect(uiHeredocDisplay(parseTerminalCommandForDisplay(raw))).toBe(
      `python3
import sys
print(1)`,
    );
  });

  it("leaves non-heredoc trimmed", () => {
    expect(uiHeredocDisplay(parseTerminalCommandForDisplay("  hof fn foo  "))).toBe(
      "hof fn foo",
    );
  });
});
