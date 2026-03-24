/**
 * Prepare registry / policy text for {@link AssistantMarkdown} without changing the markdown
 * renderer: dedent docstring-style indentation (GFM treats 4+ leading spaces as a code block)
 * and detect duplicate guidance so the composer can omit redundant sections.
 */

/** Mirrors CPython 3.12 ``inspect.cleandoc`` (expandtabs + margin on lines after the first). */
export function cleandoc(doc: string): string {
  const lines = doc.replace(/\t/g, "    ").split("\n");
  let margin = Number.POSITIVE_INFINITY;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i]!;
    const stripped = line.replace(/^ +/, "");
    if (stripped.length > 0) {
      const indent = line.length - stripped.length;
      margin = Math.min(margin, indent);
    }
  }
  if (!Number.isFinite(margin)) {
    margin = 0;
  }
  const cleaned: string[] = [];
  if (lines.length > 0) {
    cleaned.push(lines[0]!.replace(/^ +/, ""));
    for (let i = 1; i < lines.length; i++) {
      const line = lines[i]!;
      if (line.length > margin) {
        cleaned.push(line.slice(margin));
      } else {
        cleaned.push(line.replace(/^ +/, ""));
      }
    }
  }
  return cleaned.join("\n").trim();
}

export function prepareSkillMarkdownField(text: string): string {
  return cleandoc(text.trim());
}

function collapseWhitespaceLower(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/**
 * True when ``snippet`` is long enough and already appears inside ``context`` (after cleandoc),
 * so a separate UI block would mostly repeat the description.
 */
export function isGuidanceRedundantInDescription(
  contextPrepared: string,
  snippetPrepared: string,
  minSnippetLength = 24,
): boolean {
  const snippet = snippetPrepared.trim();
  if (snippet.length < minSnippetLength) {
    return false;
  }
  const ctx = collapseWhitespaceLower(contextPrepared);
  const sn = collapseWhitespaceLower(snippet);
  if (!ctx || !sn) {
    return false;
  }
  return ctx.includes(sn);
}
