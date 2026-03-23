/**
 * Scoped highlight.js token colors mapped to app-shell semantic tokens.
 * Injected once under `.hof-agent-md` (see AssistantMarkdown).
 */
export const HLJS_SCOPED_CSS = `
.hof-agent-md pre code.hljs {
  display: block;
  overflow-x: auto;
  color: var(--color-foreground);
  background: transparent;
}
.hof-agent-md code.hljs {
  padding: 0;
}
.hof-agent-md .hljs-keyword,
.hof-agent-md .hljs-selector-tag,
.hof-agent-md .hljs-subst,
.hof-agent-md .hljs-section,
.hof-agent-md .hljs-bullet {
  color: var(--color-accent);
}
.hof-agent-md .hljs-string,
.hof-agent-md .hljs-regexp,
.hof-agent-md .hljs-addition,
.hof-agent-md .hljs-attribute,
.hof-agent-md .hljs-symbol,
.hof-agent-md .hljs-template-tag,
.hof-agent-md .hljs-template-variable {
  color: color-mix(in srgb, var(--color-foreground) 72%, var(--color-accent) 28%);
}
.hof-agent-md .hljs-comment,
.hof-agent-md .hljs-quote,
.hof-agent-md .hljs-doctag,
.hof-agent-md .hljs-meta,
.hof-agent-md .hljs-meta-keyword {
  color: var(--color-secondary);
  font-style: italic;
}
.hof-agent-md .hljs-number,
.hof-agent-md .hljs-literal,
.hof-agent-md .hljs-link {
  color: color-mix(in srgb, var(--color-accent) 55%, var(--color-foreground) 45%);
}
.hof-agent-md .hljs-title,
.hof-agent-md .hljs-name,
.hof-agent-md .hljs-selector-id,
.hof-agent-md .hljs-selector-class,
.hof-agent-md .hljs-built_in,
.hof-agent-md .hljs-type {
  color: color-mix(in srgb, var(--color-foreground) 88%, var(--color-accent) 12%);
  font-weight: 600;
}
.hof-agent-md .hljs-variable,
.hof-agent-md .hljs-params,
.hof-agent-md .hljs-deletion,
.hof-agent-md .hljs-formula {
  color: var(--color-foreground);
}
.hof-agent-md .hljs-emphasis { font-style: italic; }
.hof-agent-md .hljs-strong { font-weight: 600; }
`.trim();
