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

function tokenWords(s: string): string[] {
  return normSegText(s)
    .toLowerCase()
    .split(/\s+/)
    .map((w) => w.replace(/[^\p{L}\p{N}]+/gu, ""))
    .filter(Boolean);
}

/** Share of *shorterWords* that appear in *longerWords* (bag intersection via set). */
function wordOverlapRatio(shorterWords: string[], longerWords: string[]): number {
  if (shorterWords.length === 0) {
    return 0;
  }
  const longSet = new Set(longerWords);
  let hits = 0;
  for (const w of shorterWords) {
    if (longSet.has(w)) {
      hits += 1;
    }
  }
  return hits / shorterWords.length;
}

/**
 * True when visible reply largely repeats the preceding reasoning (exact, prefix/substring,
 * or high word overlap on the shorter side).
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
  const wr = tokenWords(r);
  const wc = tokenWords(c);
  if (wr.length === 0 || wc.length === 0) {
    return false;
  }
  const short = wr.length <= wc.length ? wr : wc;
  const long = wr.length <= wc.length ? wc : wr;
  if (short.length < 4) {
    return false;
  }
  return wordOverlapRatio(short, long) >= 0.8;
}

/** Opening of assistant reply (first ~200 chars) for overlap checks. */
function contentOpeningWindow(content: string, maxChars: number): string {
  const t = normSegText(content);
  if (t.length <= maxChars) {
    return t;
  }
  const slice = t.slice(0, maxChars);
  const lastSpace = slice.lastIndexOf(" ");
  return lastSpace > 40 ? slice.slice(0, lastSpace) : slice;
}

/**
 * Word-overlap between two strings using up to *maxWords* tokens each (opening focus).
 */
function openingWordOverlap(a: string, b: string, maxWords: number): number {
  const wa = tokenWords(a).slice(0, maxWords);
  const wb = tokenWords(b).slice(0, maxWords);
  if (wa.length === 0 || wb.length === 0) {
    return 0;
  }
  const short = wa.length <= wb.length ? wa : wb;
  const long = wa.length <= wb.length ? wb : wa;
  return wordOverlapRatio(short, long);
}

const GREETING_STOPWORDS = new Set([
  "hi",
  "hello",
  "hey",
  "there",
  "how",
  "can",
  "could",
  "i",
  "help",
  "you",
  "your",
  "today",
  "assist",
  "do",
  "for",
  "with",
]);

/** True when a short clause is mostly generic chat-offer wording (draft greeting). */
function isGreetingHeavyClause(s: string): boolean {
  const w = tokenWords(s);
  if (w.length === 0 || w.length > 16) {
    return false;
  }
  let hits = 0;
  for (const x of w) {
    if (GREETING_STOPWORDS.has(x)) {
      hits += 1;
    }
  }
  if (w.length <= 3) {
    return hits >= 1 && w.some((x) => x === "hi" || x === "hello" || x === "hey");
  }
  return hits >= 3;
}

/**
 * Drop leading reasoning sentences that mainly repeat the start of the visible reply
 * (e.g. model drafts "Hi! How can I help…" in thinking then says "Hi there! …" in reply).
 */
function stripReasoningPrefixOverlappingReply(reasoning: string, content: string): string {
  let r = reasoning.trim();
  const open = contentOpeningWindow(content, 220);
  if (!r || !open) {
    return r;
  }
  const sentenceSplit = /(?<=[.!?…])\s+/u;
  let parts = r.split(sentenceSplit).map((p) => p.trim()).filter(Boolean);
  const overlapThreshold = 0.52;
  while (parts.length > 0) {
    const first = parts[0]!;
    if (first.length >= 6 && openingWordOverlap(first, open, 14) >= overlapThreshold) {
      parts = parts.slice(1);
      continue;
    }
    if (isGreetingHeavyClause(first)) {
      parts = parts.slice(1);
      continue;
    }
    break;
  }
  return parts.join(" ").trim();
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

/** Do not drop reasoning that still has substantive text after overlap trimming (avoids “thinking vanished”). */
const MIN_SUBSTANTIVE_REASONING_CHARS = 40;

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
      const trimmed = stripReasoningPrefixOverlappingReply(cur.text, next.text);
      if (!trimmed.trim()) {
        out.push(next);
        i++;
        continue;
      }
      if (
        isNearDuplicateSegText(trimmed, next.text) &&
        trimmed.trim().length <= MIN_SUBSTANTIVE_REASONING_CHARS
      ) {
        out.push(next);
        i++;
        continue;
      }
      out.push({ kind: "reasoning", text: trimmed });
      continue;
    }
    out.push(cur);
  }
  const merged = mergeAdjacentContentSegments(mergeAdjacentReasoningSegments(out));
  return merged.filter(
    (s) => s.kind !== "reasoning" || s.text.trim().length > 0,
  );
}
