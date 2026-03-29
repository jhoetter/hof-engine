"use client";

import { createLowlight, common } from "lowlight";
import type { Root } from "hast";
import { useMemo, type ReactNode } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { TERMINAL_CMD_HLJS_SCOPED_CSS } from "./markdown/hljsTokens";
import {
  displayShellInvocationFromOpener,
  parseTerminalCommandForDisplay,
} from "./terminalCommandDisplay";

const lowlight = createLowlight(common);

/** Detect language for shell / Python snippets in the terminal command block. */
export function detectTerminalCommandLanguage(code: string): string {
  const t = code.trim();
  if (!t) {
    return "bash";
  }
  const firstLine = t.split(/\r?\n/)[0] ?? "";
  if (/^(hof|curl|wget|cd|export|source)\s/i.test(firstLine)) {
    return "bash";
  }
  if (/^\$\s/.test(firstLine)) {
    return "bash";
  }
  if (/^(python3?|python)\s/i.test(firstLine)) {
    return "python";
  }
  if (
    /^(import |from |def |class |#|@|\s*"""|\s*''')/m.test(t) ||
    /\bprint\s*\(/.test(t)
  ) {
    return "python";
  }
  if (/^\s*\{\s*"name"\s*:/.test(t)) {
    return "json";
  }
  return "bash";
}

/** First token of the opener line, basename only (`/opt/python3` → `python3`). */
function heredocOpenerExecutable(openerLine: string): string {
  const first = openerLine.trim().split(/\s+/)[0] ?? "";
  if (!first) {
    return "";
  }
  const base = first.includes("/") ? (first.split("/").pop() ?? first) : first;
  return base.toLowerCase();
}

/**
 * Interpreter basename → lowlight grammar. Unlisted executables fall back to `bash` (safe default).
 * Add entries here instead of one-off regexes when supporting new heredoc drivers.
 */
const HEREDOC_BODY_LANG = new Map<string, string>([
  ["python", "python"],
  ["python3", "python"],
  ["node", "javascript"],
  ["nodejs", "javascript"],
  ["bash", "bash"],
  ["sh", "bash"],
  ["zsh", "bash"],
  ["fish", "bash"],
  ["dash", "bash"],
  ["ash", "bash"],
  ["ksh", "bash"],
]);

export function inferHeredocBodyLanguage(shellOpenerLine: string): string {
  const exe = heredocOpenerExecutable(shellOpenerLine);
  return HEREDOC_BODY_LANG.get(exe) ?? "bash";
}

function highlightToReact(code: string, lang: string): ReactNode {
  let tree: Root;
  try {
    tree = lowlight.highlight(lang, code);
  } catch {
    try {
      tree = lowlight.highlight("bash", code);
    } catch {
      return code;
    }
  }
  const el = toJsxRuntime(tree, {
    Fragment,
    jsx,
    jsxs,
    elementAttributeNameCase: "react",
  });
  return el;
}

export type TerminalCommandEmphasis = "command" | "continuation";

export function TerminalCommandHighlight({
  code,
  className = "",
  variant = "block",
  lang: langProp,
  emphasis = "command",
}: {
  code: string;
  className?: string;
  /** `inline`: same line as `$ ` prefix in compact tool cards; `block`: full-width row under `$`. */
  variant?: "block" | "inline";
  /** When set, skips language detection (used for heredoc openers / closers). */
  lang?: string;
  /**
   * `command`: bright + semibold (typed shell line). `continuation`: muted (indented heredoc / stdin
   * body — any language, not Python-specific).
   */
  emphasis?: TerminalCommandEmphasis;
}) {
  const lang = useMemo(
    () => langProp ?? detectTerminalCommandLanguage(code),
    [code, langProp],
  );
  const body = useMemo(
    () => highlightToReact(code, lang),
    [code, lang],
  );
  const display =
    variant === "inline" ? "inline whitespace-pre-wrap align-top" : "block";

  const tone =
    emphasis === "command"
      ? "font-semibold text-foreground"
      : "font-normal text-foreground";

  return (
    <code
      className={`hof-terminal-cmd hljs language-${lang} ${display} overflow-x-auto bg-transparent p-0 font-mono text-[11px] leading-snug ${tone} ${className}`}
    >
      {body}
    </code>
  );
}

/**
 * Like {@link TerminalCommandHighlight}, but for heredocs shows **interpreter only** (no `<<` /
 * delimiter) plus **embedded script** (e.g. Python). Closing delimiter lines are omitted.
 */
export function TerminalInvocationHighlight({
  code,
  variant = "block",
  className = "",
}: {
  code: string;
  /** Applied when `variant` is `inline` (compact cards). Ignored for default `block` (fragment output). */
  className?: string;
  variant?: "block" | "inline";
}) {
  const parsed = useMemo(
    () => parseTerminalCommandForDisplay(code.trim()),
    [code],
  );

  if (parsed.kind === "single") {
    return (
      <TerminalCommandHighlight
        code={parsed.text}
        variant={variant}
        emphasis="command"
        className={className}
      />
    );
  }

  const embedLang = inferHeredocBodyLanguage(parsed.shellOpener);
  const shellShown = displayShellInvocationFromOpener(parsed.shellOpener);
  /* Indented block: stdin / here-doc body under the interpreter (any language). */
  const continuationShell = (node: ReactNode) => (
    <div className="mt-1 block min-w-0 max-w-full border-l-2 border-[color:color-mix(in_srgb,var(--color-border)_50%,transparent)] pl-3">
      <div className="opacity-[0.88]">{node}</div>
    </div>
  );

  const inner = (
    <>
      {shellShown.length > 0 ? (
        <TerminalCommandHighlight
          code={shellShown}
          lang="bash"
          variant="block"
          emphasis="command"
          className="block min-w-0 max-w-full"
        />
      ) : null}
      {parsed.body.length > 0
        ? continuationShell(
            <TerminalCommandHighlight
              code={parsed.body}
              lang={embedLang}
              variant="block"
              emphasis="continuation"
              className="block min-w-0 max-w-full"
            />,
          )
        : null}
    </>
  );

  if (variant === "inline") {
    return (
      <span
        className={`inline-block min-w-0 max-w-full align-top whitespace-pre-wrap ${className}`.trim()}
      >
        {inner}
      </span>
    );
  }

  return <>{inner}</>;
}

/** Injected once next to agent chat (see `HofAgentChat`) so terminal command blocks get hljs token colors. */
export function TerminalCommandHljsStyle() {
  return <style>{TERMINAL_CMD_HLJS_SCOPED_CSS}</style>;
}
