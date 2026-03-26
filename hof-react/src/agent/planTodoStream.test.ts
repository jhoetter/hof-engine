import { describe, expect, it } from "vitest";
import type { HofStreamEvent } from "../hooks/streamHofFunction";
import {
  applyPlanTodoWireResolution,
  mergePlanTodoDoneIndices,
  PLAN_TODO_UPDATE_EVENT_TYPE,
  resolvePlanTodoUpdateWireEvent,
} from "./planTodoStream";

describe("mergePlanTodoDoneIndices", () => {
  it("merges and sorts uniquely", () => {
    expect(mergePlanTodoDoneIndices([0, 2], [1, 2])).toEqual([0, 1, 2]);
  });
});

describe("resolvePlanTodoUpdateWireEvent", () => {
  it("returns null for other event types", () => {
    expect(resolvePlanTodoUpdateWireEvent({ type: "final" }, "- [ ] A")).toBe(
      null,
    );
  });

  it("normalizes 1-based wire against plan markdown", () => {
    const ev = {
      type: PLAN_TODO_UPDATE_EVENT_TYPE,
      done_indices: [1, 2, 3],
    } as HofStreamEvent;
    const md = "# T\n\n- [ ] a\n- [ ] b\n- [ ] c\n- [ ] d\n- [ ] e";
    const r = resolvePlanTodoUpdateWireEvent(ev, md);
    expect(r).not.toBeNull();
    expect(r!.didNormalize).toBe(true);
    expect(r!.indices).toEqual([0, 1, 2]);
    expect((r!.event as { done_indices: number[] }).done_indices).toEqual([
      0, 1, 2,
    ]);
  });
});

describe("applyPlanTodoWireResolution", () => {
  it("passes through non-plan-todo events", () => {
    const ev = { type: "phase", phase: "model" } as HofStreamEvent;
    const out = applyPlanTodoWireResolution(ev, "- [ ] One");
    expect(out.evForBlocks).toBe(ev);
    expect(out.mergeIndices).toEqual([]);
  });
});
