/** Reasoning vs visible reply chunks from NDJSON ``segment_start`` + deltas (llm-markdown 0.3.8+). */
export type AssistantStreamSegment = {
  kind: "reasoning" | "content";
  text: string;
};

export function appendAssistantStreamSegmentChunk(
  segments: AssistantStreamSegment[] | undefined,
  kind: "reasoning" | "content",
  chunk: string,
): AssistantStreamSegment[] {
  const segs = segments ? [...segments] : [];
  const tail = segs[segs.length - 1];
  if (tail && tail.kind === kind) {
    segs[segs.length - 1] = { kind, text: tail.text + chunk };
  } else {
    segs.push({ kind, text: chunk });
  }
  return segs;
}

function normSegText(s: string): string {
  return s.trim().replace(/\s+/g, " ");
}

/**
 * True when visible reply repeats the preceding reasoning (exact match or substantive
 * substring containment — no fuzzy word-overlap tuning).
 */
function isNearDuplicateSegText(reasoning: string, content: string): boolean {
  const r = normSegText(reasoning);
  const c = normSegText(content);
  if (!r || !c) {
    return false;
  }
  if (r === c) {
    return true;
  }
  const minLen = Math.min(r.length, c.length);
  if (minLen >= 10) {
    if (c.startsWith(r) || r.startsWith(c)) {
      return true;
    }
    if (c.includes(r) || r.includes(c)) {
      return true;
    }
  }
  return false;
}

/**
 * Collapse consecutive ``reasoning`` segments (duplicate ``segment_start`` from the
 * wire, or Phase A + Phase B) into one — avoids multiple THINKING headers / empty shells.
 */
export function mergeAdjacentReasoningSegments(
  segments: AssistantStreamSegment[],
): AssistantStreamSegment[] {
  const out: AssistantStreamSegment[] = [];
  for (const s of segments) {
    const tail = out[out.length - 1];
    if (s.kind === "reasoning" && tail?.kind === "reasoning") {
      const merged = `${tail.text}\n\n${s.text}`.trim();
      out[out.length - 1] = { kind: "reasoning", text: merged };
    } else {
      out.push({ ...s });
    }
  }
  return out;
}

/** Merge consecutive reply segments so one model turn does not render as multiple bubbles. */
export function mergeAdjacentContentSegments(
  segments: AssistantStreamSegment[],
): AssistantStreamSegment[] {
  const out: AssistantStreamSegment[] = [];
  for (const s of segments) {
    const tail = out[out.length - 1];
    if (s.kind === "content" && tail?.kind === "content") {
      const merged = `${tail.text}\n\n${s.text}`.trim();
      out[out.length - 1] = { kind: "content", text: merged };
    } else {
      out.push({ ...s });
    }
  }
  return out;
}

/** Drop trailing empty ``content`` shells and hide reasoning that duplicates the following reply. */
export function normalizeAssistantStreamSegments(
  segments: AssistantStreamSegment[],
): AssistantStreamSegment[] {
  if (segments.length === 0) {
    return segments;
  }
  const trimmedEnd = [...segments];
  while (
    trimmedEnd.length > 0 &&
    trimmedEnd[trimmedEnd.length - 1]!.kind === "content" &&
    !trimmedEnd[trimmedEnd.length - 1]!.text.trim()
  ) {
    trimmedEnd.pop();
  }
  const out: AssistantStreamSegment[] = [];
  for (let i = 0; i < trimmedEnd.length; i++) {
    const cur = trimmedEnd[i]!;
    const next = trimmedEnd[i + 1];
    if (cur.kind === "reasoning" && next?.kind === "content") {
      if (isNearDuplicateSegText(cur.text, next.text)) {
        out.push(next);
        i++;
        continue;
      }
      out.push(cur);
      continue;
    }
    out.push(cur);
  }
  const merged = mergeAdjacentContentSegments(mergeAdjacentReasoningSegments(out));
  return merged.filter(
    (s) => s.kind !== "reasoning" || s.text.trim().length > 0,
  );
}
