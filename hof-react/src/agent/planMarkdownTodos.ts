/**
 * Parse GitHub-style task list lines from plan markdown for execution UI.
 * Indices follow top-to-bottom order of `- [ ]` / `- [x]` lines only.
 */
export type ParsedPlanTodo = {
  index: number;
  line: string;
  label: string;
  sourceChecked: boolean;
};

const TASK_LINE = /^(\s*[-*]\s+)\[([ xX])\]\s*(.+)\s*$/;

/** True if the line starts a GFM task item (`- [ ]` / `* [x]`, including while streaming). */
function lineStartsTaskListItem(line: string): boolean {
  return /^\s*[-*]\s+\[/.test(line);
}

/**
 * Returns markdown from the first task-list line onward. Use during plan discovery so preamble
 * (“I will load data…”) never appears inside the plan preview. Returns "" if no task line exists yet.
 */
export function sliceMarkdownFromFirstTaskListLine(markdown: string): string {
  const lines = (markdown ?? "").split(/\r?\n/);
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lineStartsTaskListItem(lines[i]!)) {
      start = i;
      break;
    }
  }
  if (start < 0) {
    return "";
  }
  return lines.slice(start).join("\n");
}

/**
 * Prefer checklist-only markdown when the model prefixed prose; otherwise keep the full reply.
 * When the reply uses a markdown heading (`# Title`) before tasks, keep the full structured plan.
 */
export function preferPlanTaskListBody(markdown: string): string {
  const trimmed = (markdown ?? "").trim();
  if (!trimmed) {
    return "";
  }
  if (/^\s*#/m.test(trimmed)) {
    return trimmed;
  }
  const sliced = sliceMarkdownFromFirstTaskListLine(trimmed);
  return sliced.length > 0 ? sliced : trimmed;
}

/** Parsed plan for Cursor-style plan card (title, description, checklist). */
export type StructuredPlan = {
  title: string;
  description: string;
  todos: ParsedPlanTodo[];
  raw: string;
};

/**
 * Split plan markdown into title (first `#` line or first non-empty line), description
 * (paragraphs before the first task line), and task list.
 */
export function parseStructuredPlan(markdown: string): StructuredPlan {
  const raw = (markdown ?? "").trim();
  if (!raw) {
    return { title: "", description: "", todos: [], raw: "" };
  }
  const lines = raw.split(/\r?\n/);
  let firstNonEmpty = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i]!.trim()) {
      firstNonEmpty = i;
      break;
    }
  }
  if (firstNonEmpty < 0) {
    return { title: "", description: "", todos: parsePlanMarkdownTodos(raw), raw };
  }
  let title = "";
  let afterTitle = firstNonEmpty + 1;
  const L0 = lines[firstNonEmpty]!.trim();
  if (L0.startsWith("#")) {
    title = L0.replace(/^#+\s*/, "").trim();
  } else {
    title = L0;
    afterTitle = firstNonEmpty + 1;
  }
  let taskStart = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lineStartsTaskListItem(lines[i]!)) {
      taskStart = i;
      break;
    }
  }
  const descParts: string[] = [];
  const descEnd = taskStart >= 0 ? taskStart : lines.length;
  for (let i = afterTitle; i < descEnd; i++) {
    const t = lines[i]!.trim();
    if (t) {
      descParts.push(t);
    }
  }
  const description = descParts.join("\n\n");
  const todos = parsePlanMarkdownTodos(raw);
  return { title, description, todos, raw };
}

export function parsePlanMarkdownTodos(markdown: string): ParsedPlanTodo[] {
  const lines = (markdown || "").split(/\r?\n/);
  const out: ParsedPlanTodo[] = [];
  let idx = 0;
  for (const line of lines) {
    const m = line.match(TASK_LINE);
    if (!m) {
      continue;
    }
    const checked = m[2].toLowerCase() === "x";
    const label = (m[3] ?? "").trim();
    out.push({
      index: idx,
      line: line.trimEnd(),
      label,
      sourceChecked: checked,
    });
    idx += 1;
  }
  return out;
}
