/**
 * Plan execution checklist progress — wire contract between engine NDJSON and React UI.
 *
 * The engine emits `{ type: "plan_todo_update", done_indices: number[] }` when
 * `hof_builtin_update_plan_todo_state` returns (see `hof/agent/stream.py`).
 * Indices are **intended** to be 0-based (top `- [ ]` line = 0). Models often send
 * human step numbers `1…n` instead; {@link normalizePlanTodoWireIndices} fixes that
 * before state and `plan_step_progress` blocks are updated.
 *
 * @see ../../docs/plan-todo-contract.md
 */
import type { HofStreamEvent } from "../hooks/streamHofFunction";
import {
  normalizePlanTodoWireIndices,
  parseStructuredPlan,
} from "./planMarkdownTodos";

export const PLAN_TODO_UPDATE_EVENT_TYPE = "plan_todo_update" as const;

export type PlanTodoWireResolution = {
  /** Pass to `applyStreamEventWithDedupe` (normalized `done_indices` when applicable). */
  event: HofStreamEvent;
  /** Indices to merge into `planTodoDoneIndices` (0-based, sorted). */
  indices: number[];
  /** True when `done_indices` was normalized against a non-empty checklist. */
  didNormalize: boolean;
};

/**
 * If `ev` is a `plan_todo_update`, normalize `done_indices` against the approved plan
 * markdown and return the event to feed the block reducer. Otherwise returns `null`
 * (caller keeps `evForBlocks = ev`).
 */
export function resolvePlanTodoUpdateWireEvent(
  ev: HofStreamEvent,
  planMarkdown: string,
): PlanTodoWireResolution | null {
  const typ = typeof ev.type === "string" ? ev.type : "";
  if (typ !== PLAN_TODO_UPDATE_EVENT_TYPE) {
    return null;
  }
  const n = parseStructuredPlan(planMarkdown.trim()).todos.length;
  const di = (ev as { done_indices?: unknown }).done_indices;
  if (!Array.isArray(di) || n <= 0) {
    return {
      event: ev,
      indices: [],
      didNormalize: false,
    };
  }
  const raw = di.map((x) => Number(x)).filter((x) => Number.isFinite(x));
  const normalized = normalizePlanTodoWireIndices(raw, n);
  return {
    event: { ...ev, done_indices: normalized } as HofStreamEvent,
    indices: normalized,
    didNormalize: true,
  };
}

/** Merge new checklist indices into persisted UI state (cumulative completion). */
export function mergePlanTodoDoneIndices(
  prev: readonly number[],
  incoming: readonly number[],
): number[] {
  const s = new Set(prev);
  for (const x of incoming) {
    s.add(x);
  }
  return Array.from(s).sort((a, b) => a - b);
}

/**
 * Single entry point for stream handlers: normalize the event (if applicable) and return
 * indices to merge into {@link mergePlanTodoDoneIndices}.
 */
export function applyPlanTodoWireResolution(
  ev: HofStreamEvent,
  planMarkdown: string,
): { evForBlocks: HofStreamEvent; mergeIndices: number[] } {
  const resolved = resolvePlanTodoUpdateWireEvent(ev, planMarkdown);
  if (!resolved) {
    return { evForBlocks: ev, mergeIndices: [] };
  }
  return {
    evForBlocks: resolved.event,
    mergeIndices: resolved.didNormalize ? resolved.indices : [],
  };
}
