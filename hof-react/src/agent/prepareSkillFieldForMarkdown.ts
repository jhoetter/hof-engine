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
  s = s.replace(
    /\(?\s*mutation\s*\(\s*confirms?\s+in\s+UI\s*\)\s*\)?\.?/gi,
    "(requires your approval in the app)",
  );
  s = s.replace(
    /(\(requires your approval in the app\)\s*){2,}/g,
    "(requires your approval in the app) ",
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

  s = s.replace(/`\s*\/\s*`/g, "`, `");

  return s.trim();
}

function paragraphStartsWithGuidanceHeading(
  firstLine: string,
  kind: "when_to_use" | "when_not_to_use",
): boolean {
  const t = firstLine.trim();
  const re =
    kind === "when_to_use"
      ? /^(#{1,6}\s+|\*{0,2}\s*)When\s+to\s+use(?:\s*\*{0,2})?\s*:?/i
      : /^(#{1,6}\s+|\*{0,2}\s*)When\s+not\s+to\s+use(?:\s*\*{0,2})?\s*:?/i;
  return re.test(t);
}

/**
 * When the API already exposes ``when_to_use`` / ``when_not_to_use`` as separate fields, drop
 * paragraphs in the description that repeat those headings so the UI does not show two blocks.
 * Operates on an already {@link prepareSkillMarkdownField}-processed string.
 */
export function stripGuidanceParagraphsForStructuredSections(
  preparedDescription: string,
  options: { showStructuredWhen: boolean; showStructuredWhenNot: boolean },
): string {
  if (!options.showStructuredWhen && !options.showStructuredWhenNot) {
    return preparedDescription;
  }
  const paras = preparedDescription.split(/\n{2,}/);
  const kept = paras.filter((para) => {
    const first = para.trim().split("\n")[0] ?? "";
    if (!first.trim()) {
      return true;
    }
    if (options.showStructuredWhen && paragraphStartsWithGuidanceHeading(first, "when_to_use")) {
      return false;
    }
    if (
      options.showStructuredWhenNot &&
      paragraphStartsWithGuidanceHeading(first, "when_not_to_use")
    ) {
      return false;
    }
    return true;
  });
  return kept.join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
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
  minSnippetLength = 16,
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
