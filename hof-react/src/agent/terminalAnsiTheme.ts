/**
 * Map ansi_up class names (`*-fg` / `*-bg`) to app-shell semantic tokens so Rich / `hof fn`
 * output in the assistant resembles a real terminal without hardcoded hex.
 */
export const TERMINAL_ANSI_SCOPED_CSS = `
.hof-terminal-ansi {
  color: var(--color-secondary);
}
.hof-terminal-ansi .ansi-black-fg { color: var(--color-tertiary); }
.hof-terminal-ansi .ansi-red-fg { color: color-mix(in srgb, var(--color-destructive) 88%, var(--color-foreground)); }
.hof-terminal-ansi .ansi-green-fg { color: color-mix(in srgb, var(--color-success) 82%, var(--color-foreground)); }
.hof-terminal-ansi .ansi-yellow-fg { color: color-mix(in srgb, var(--color-foreground) 55%, var(--color-bit-orange, var(--color-accent)) 45%); }
.hof-terminal-ansi .ansi-blue-fg { color: var(--color-accent); }
.hof-terminal-ansi .ansi-magenta-fg { color: color-mix(in srgb, var(--color-secondary) 40%, var(--color-accent) 60%); }
.hof-terminal-ansi .ansi-cyan-fg { color: color-mix(in srgb, var(--color-accent) 45%, var(--color-success) 55%); }
.hof-terminal-ansi .ansi-white-fg { color: var(--color-foreground); }
.hof-terminal-ansi .ansi-bright-black-fg { color: var(--color-secondary); }
.hof-terminal-ansi .ansi-bright-red-fg { color: color-mix(in srgb, var(--color-destructive) 95%, var(--color-foreground)); }
.hof-terminal-ansi .ansi-bright-green-fg { color: var(--color-success); }
.hof-terminal-ansi .ansi-bright-yellow-fg { color: color-mix(in srgb, var(--color-foreground) 35%, var(--color-bit-orange, var(--color-accent)) 65%); }
.hof-terminal-ansi .ansi-bright-blue-fg { color: color-mix(in srgb, var(--color-accent) 70%, var(--color-foreground) 30%); }
.hof-terminal-ansi .ansi-bright-magenta-fg { color: color-mix(in srgb, var(--color-accent) 55%, var(--color-secondary) 45%); }
.hof-terminal-ansi .ansi-bright-cyan-fg { color: color-mix(in srgb, var(--color-accent) 50%, var(--color-success) 50%); }
.hof-terminal-ansi .ansi-bright-white-fg { color: var(--color-foreground); }

.hof-terminal-ansi .ansi-black-bg { background-color: color-mix(in srgb, var(--color-foreground) 12%, transparent); }
.hof-terminal-ansi .ansi-red-bg { background-color: color-mix(in srgb, var(--color-destructive) 22%, transparent); }
.hof-terminal-ansi .ansi-green-bg { background-color: color-mix(in srgb, var(--color-success) 18%, transparent); }
.hof-terminal-ansi .ansi-yellow-bg { background-color: color-mix(in srgb, var(--color-bit-orange, var(--color-accent)) 18%, transparent); }
.hof-terminal-ansi .ansi-blue-bg { background-color: color-mix(in srgb, var(--color-accent) 18%, transparent); }
.hof-terminal-ansi .ansi-magenta-bg { background-color: color-mix(in srgb, var(--color-accent) 12%, var(--color-secondary) 10%, transparent); }
.hof-terminal-ansi .ansi-cyan-bg { background-color: color-mix(in srgb, var(--color-accent) 12%, var(--color-success) 12%, transparent); }
.hof-terminal-ansi .ansi-white-bg { background-color: color-mix(in srgb, var(--color-foreground) 8%, transparent); }
.hof-terminal-ansi .ansi-bright-black-bg { background-color: color-mix(in srgb, var(--color-secondary) 14%, transparent); }
.hof-terminal-ansi .ansi-bright-red-bg { background-color: color-mix(in srgb, var(--color-destructive) 26%, transparent); }
.hof-terminal-ansi .ansi-bright-green-bg { background-color: color-mix(in srgb, var(--color-success) 24%, transparent); }
.hof-terminal-ansi .ansi-bright-yellow-bg { background-color: color-mix(in srgb, var(--color-bit-orange, var(--color-accent)) 24%, transparent); }
.hof-terminal-ansi .ansi-bright-blue-bg { background-color: color-mix(in srgb, var(--color-accent) 24%, transparent); }
.hof-terminal-ansi .ansi-bright-magenta-bg { background-color: color-mix(in srgb, var(--color-accent) 18%, transparent); }
.hof-terminal-ansi .ansi-bright-cyan-bg { background-color: color-mix(in srgb, var(--color-accent) 16%, var(--color-success) 16%, transparent); }
.hof-terminal-ansi .ansi-bright-white-bg { background-color: color-mix(in srgb, var(--color-foreground) 12%, transparent); }
`.trim();
