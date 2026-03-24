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

/**
 * Light-touch cleanup for tool/policy prose before markdown: stray spaces before punctuation,
 * sloppy parentheses, repeated blank lines, and a few recurring end-user phrasing patterns.
 * Conservative: skips lines that look like indented code (4+ leading spaces) or ``` fences.
 */
function polishProseMarkdownSource(src: string): string {
  let s = src.replace(/\r\n/g, "\n");

  s = s.replace(
    /\(mutation\s*[—–-]\s*confirms?\s+in\s+(?:the\s+)?(?:assistant\s+)?UI\)/gi,
    "(requires your approval in the app)",
  );
  s = s.replace(/\)\s+\./g, ").");
  s = s.replace(/#\s+\)/g, "#)");

  s = s.replace(/\n{3,}/g, "\n\n");

  const lines = s.split("\n");
  s = lines
    .map((line) => {
      const trimmedEnd = line.replace(/[ \t]+$/g, "");
      const t = trimmedEnd.trimStart();
      if (t.startsWith("```")) {
        return trimmedEnd;
      }
      if (/^ {4,}\S/.test(trimmedEnd)) {
        return trimmedEnd;
      }
      let out = trimmedEnd.replace(/[ \t]{2,}/g, " ");
      out = out.replace(/\s+([.,;!?])(?=\s|$)/g, "$1");
      out = out.replace(/([\w)])\s+(:)(?=\s|$)/g, "$1$2");
      return out;
    })
    .join("\n");

  s = s.replace(/`([^`\n]*?)`/g, (full, inner: string) => {
    const t = String(inner).trim();
    if (!t) {
      return full;
    }
    return `\`${t}\``;
  });

  return s.trim();
}

export function prepareSkillMarkdownField(text: string): string {
  return polishProseMarkdownSource(cleandoc(text.trim()));
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
