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

/**
 * ``Thinking`` timer, shimmer, and live popover: active only during the **reasoning** phase of
 * the turn (before the content segment receives text). Once reply tokens arrive, the row stays
 * mounted but switches to settled “Thought” + frozen duration — even if the assistant row is
 * still ``streaming`` (long table, etc.).
 *
 * An empty trailing ``content`` segment from ``segment_start: content`` does not end the phase.
 */
export function reasoningPhaseTickingLive(
  merged: AssistantStreamSegment[],
  segIndex: number,
  lastReasoningIndex: number,
  wireStreaming: boolean,
): boolean {
  if (!wireStreaming || segIndex !== lastReasoningIndex) {
    return false;
  }
  const seg = merged[segIndex];
  if (seg?.kind !== "reasoning") {
    return false;
  }
  const next = merged[segIndex + 1];
  if (!next || next.kind !== "content") {
    return true;
  }
  return !next.text.trim();
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

/** Drop trailing empty ``content`` shells. Reasoning is kept even when similar to the reply so multi-round tool flows still show each thinking phase. */
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
  const merged = mergeAdjacentContentSegments(
    mergeAdjacentReasoningSegments(trimmedEnd),
  );
  const out = merged.filter((s, i, arr) => {
    if (s.kind !== "reasoning") {
      return true;
    }
    if (s.text.trim().length > 0) {
      return true;
    }
    // Keep empty reasoning before non-empty content: some streams only fill the content
    // channel while the UI still shows a distinct thinking phase.
    return arr
      .slice(i + 1)
      .some((t) => t.kind === "content" && t.text.trim().length > 0);
  });
  return out;
}
