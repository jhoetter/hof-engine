/**
 * Preprocess assistant markdown so accidental pipe-heavy plain text does not
 * become GFM tables (which pick up table borders in the UI).
 *
 * Only touches lines **outside** fenced code blocks (` ``` `).
 * Real pipe tables (header row + delimiter row with `---`) are left unchanged.
 */

/** One GFM table cell in the delimiter row: :---, ---, :---:, etc. */
function isDelimiterCell(cell: string): boolean {
  const c = cell.trim();
  return /^:?-{3,}:?$/.test(c);
}

function isGfmDelimiterLine(line: string): boolean {
  const t = line.trim();
  if (!t.includes("|") || !t.includes("-")) {
    return false;
  }
  const cells = t
    .split("|")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  return cells.length > 0 && cells.every(isDelimiterCell);
}

/** Row that participates in a pipe-table run (leading `|`). */
function isPipeTableRowLine(line: string): boolean {
  return /^\s*\|/.test(line);
}

function neutralizePipeLine(line: string): string {
  return line.replace(/\|/g, "&#124;");
}

function neutralizeSpuriousPipeBlocks(lines: string[]): void {
  let i = 0;
  while (i < lines.length) {
    if (!isPipeTableRowLine(lines[i]!)) {
      i += 1;
      continue;
    }
    const start = i;
    while (i < lines.length && isPipeTableRowLine(lines[i]!)) {
      i += 1;
    }
    const end = i;
    const runLen = end - start;
    if (runLen < 2) {
      continue;
    }
    if (isGfmDelimiterLine(lines[start + 1]!)) {
      continue;
    }
    for (let k = start; k < end; k++) {
      lines[k] = neutralizePipeLine(lines[k]!);
    }
  }
}

/**
 * Prepare raw assistant markdown for {@link ReactMarkdown} / `remark-gfm`.
 */
export function prepareAssistantMarkdownSource(source: string): string {
  const lines = source.split(/\r?\n/);
  let inFence = false;
  const out: string[] = [];
  let buf: string[] = [];

  const flushBuf = () => {
    if (buf.length === 0) {
      return;
    }
    neutralizeSpuriousPipeBlocks(buf);
    out.push(...buf);
    buf = [];
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flushBuf();
      inFence = !inFence;
      out.push(line);
      continue;
    }
    if (inFence) {
      out.push(line);
    } else {
      buf.push(line);
    }
  }
  flushBuf();

  return out.join("\n");
}
