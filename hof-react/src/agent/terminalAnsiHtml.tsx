"use client";

import { AnsiUp } from "ansi_up";
import { TERMINAL_ANSI_SCOPED_CSS } from "./terminalAnsiTheme";

const ansiUp = new AnsiUp();
ansiUp.use_classes = true;

/** Escape sequences → HTML spans (classes styled by {@link TERMINAL_ANSI_SCOPED_CSS}). */
export function terminalOutputAnsiToHtml(text: string): string {
  return ansiUp.ansi_to_html(text);
}

/** Inject once next to agent chat (see `HofAgentMessages`). */
export function TerminalAnsiStyle() {
  return <style>{TERMINAL_ANSI_SCOPED_CSS}</style>;
}
