import { describe, expect, it } from "vitest";
import {
  applyStreamEvent,
  segmentLiveBlocks,
  type LiveBlock,
} from "./hofAgentChatModel";

describe("mutation_applied stream event", () => {
  it("creates a mutation_applied LiveBlock", () => {
    const prev: LiveBlock[] = [];
    const next = applyStreamEvent(
      prev,
      {
        type: "mutation_applied",
        pending_id: "pid-1",
        name: "create_expense",
        tool_call_id: "call_x",
        post_apply_review: {
          label: "Manager review",
          url: "http://localhost:8001/inbox",
          path: "/inbox",
        },
      },
      { assistantStreamPhase: null },
    );
    expect(next).toHaveLength(1);
    const b = next[0];
    expect(b?.kind).toBe("mutation_applied");
    if (b?.kind !== "mutation_applied") {
      return;
    }
    expect(b.pending_id).toBe("pid-1");
    expect(b.name).toBe("create_expense");
    expect(b.tool_call_id).toBe("call_x");
    expect(b.post_apply_review.label).toBe("Manager review");
    expect(b.post_apply_review.url).toBe("http://localhost:8001/inbox");
    expect(b.post_apply_review.path).toBe("/inbox");
  });

  it("accepts label-only post_apply_review", () => {
    const next = applyStreamEvent(
      [],
      {
        type: "mutation_applied",
        pending_id: "p",
        name: "x",
        post_apply_review: { label: "Legal" },
      },
      { assistantStreamPhase: null },
    );
    expect(next[0]?.kind).toBe("mutation_applied");
    if (next[0]?.kind !== "mutation_applied") {
      return;
    }
    expect(next[0].post_apply_review.label).toBe("Legal");
    expect(next[0].post_apply_review.url).toBeUndefined();
  });

  it("ignores invalid payload", () => {
    const prev: LiveBlock[] = [{ kind: "assistant", id: "a", text: "hi", streaming: false }];
    const next = applyStreamEvent(
      prev,
      {
        type: "mutation_applied",
        pending_id: "",
        name: "x",
        post_apply_review: { label: "L" },
      },
      { assistantStreamPhase: null },
    );
    expect(next).toEqual(prev);
  });
});

describe("segmentLiveBlocks + mutation_applied", () => {
  it("folds mutation_applied into tool_group when pending_id matches", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "tool_call",
        id: "c1",
        name: "create_expense",
        cli_line: "hof fn create_expense",
      },
      {
        kind: "mutation_pending",
        id: "m1",
        pending_id: "pid-1",
        name: "create_expense",
        cli_line: "hof fn create_expense",
      },
      {
        kind: "tool_result",
        id: "r1",
        name: "create_expense",
        summary: "ok",
        pending_confirmation: true,
      },
      {
        kind: "mutation_applied",
        id: "a1",
        pending_id: "pid-1",
        name: "create_expense",
        post_apply_review: { label: "Manager review", path: "/inbox" },
      },
    ];
    const segs = segmentLiveBlocks(blocks);
    expect(segs).toHaveLength(1);
    expect(segs[0]?.type).toBe("tool_group");
    if (segs[0]?.type !== "tool_group") {
      return;
    }
    expect(segs[0].mutationApplied?.post_apply_review.label).toBe("Manager review");
  });

  it("uses last tool_result per tool_call_id so resume replaces pending row", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "tool_call",
        id: "c1",
        name: "create_expense",
        cli_line: "hof fn create_expense",
        tool_call_id: "tid_a",
      },
      {
        kind: "mutation_pending",
        id: "m1",
        pending_id: "pid-1",
        name: "create_expense",
        cli_line: "hof fn create_expense",
      },
      {
        kind: "tool_result",
        id: "r_pending",
        name: "create_expense",
        summary: "wait",
        pending_confirmation: true,
        status_code: 202,
        tool_call_id: "tid_a",
      },
      {
        kind: "assistant",
        id: "as1",
        text: "done",
        streaming: false,
      },
      {
        kind: "tool_result",
        id: "r_ok",
        name: "create_expense",
        summary: "created",
        ok: true,
        status_code: 200,
        tool_call_id: "tid_a",
      },
    ];
    const segs = segmentLiveBlocks(blocks);
    const tg = segs.find((s) => s.type === "tool_group");
    expect(tg?.type).toBe("tool_group");
    if (tg?.type !== "tool_group") {
      return;
    }
    expect(tg.result?.id).toBe("r_ok");
    expect(tg.result?.pending_confirmation).toBeUndefined();
    expect(tg.result?.ok).toBe(true);
    expect(segs.filter((s) => s.type === "single")).toHaveLength(1);
  });
});
