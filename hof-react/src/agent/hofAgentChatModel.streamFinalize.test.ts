import { describe, expect, it } from "vitest";
import {
  applyStreamEvent,
  compactBlocksForHistory,
  confirmationFooterIconsFromOutcomes,
  finalizeLiveBlocksAfterUserStop,
  finalizePlanFromTerminalEvent,
  inferAssistantUiLane,
} from "./hofAgentChatModel";
import type { LiveBlock } from "./hofAgentChatModel";

const ctx = { assistantStreamPhase: null as "model" | "summary" | null };

describe("applyStreamEvent streaming caret / structured steps", () => {
  it("sets assistant streaming false on tool_call before assistant_done", () => {
    let blocks: LiveBlock[] = [];
    blocks = applyStreamEvent(
      blocks,
      { type: "phase", phase: "model", round: 0 },
      ctx,
    );
    blocks = applyStreamEvent(blocks, { type: "assistant_delta", text: "Done." }, ctx);
    const beforeTool = blocks[blocks.length - 1];
    expect(beforeTool?.kind).toBe("assistant");
    if (beforeTool?.kind === "assistant") {
      expect(beforeTool.streaming).toBe(true);
    }

    blocks = applyStreamEvent(
      blocks,
      {
        type: "tool_call",
        name: "create_expense",
        arguments: "{}",
        cli_line: "hof fn create_expense",
      },
      ctx,
    );

    const asst = blocks.find((b) => b.kind === "assistant");
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.streaming).toBe(false);
      expect(asst.pendingStreamFinalize).toBe(true);
      expect(asst.text).toBe("Done.");
    }
    expect(blocks.some((b) => b.kind === "tool_call")).toBe(true);
  });

  it("tool_call maps display_title to displayTitle on the block", () => {
    let blocks: LiveBlock[] = [];
    blocks = applyStreamEvent(
      blocks,
      { type: "phase", phase: "model", round: 0 },
      ctx,
    );
    blocks = applyStreamEvent(
      blocks,
      {
        type: "tool_call",
        name: "register_receipt_upload",
        arguments: "{}",
        cli_line: "hof fn register_receipt_upload",
        display_title: "Uploading invoice_72.pdf",
      },
      ctx,
    );
    const tc = blocks.find((b) => b.kind === "tool_call");
    expect(tc?.kind).toBe("tool_call");
    if (tc?.kind === "tool_call") {
      expect(tc.displayTitle).toBe("Uploading invoice_72.pdf");
    }
  });

  it("assistant_done still finalizes assistant after tool_call pre-close", () => {
    let blocks: LiveBlock[] = [];
    blocks = applyStreamEvent(
      blocks,
      { type: "phase", phase: "model", round: 0 },
      ctx,
    );
    blocks = applyStreamEvent(blocks, { type: "assistant_delta", text: "Hi" }, ctx);
    blocks = applyStreamEvent(
      blocks,
      {
        type: "tool_call",
        name: "x",
        arguments: "{}",
        cli_line: "hof fn x",
      },
      ctx,
    );
    blocks = applyStreamEvent(
      blocks,
      { type: "assistant_done", finish_reason: "tool_calls" },
      ctx,
    );

    const asst = blocks.find((b) => b.kind === "assistant");
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.streaming).toBe(false);
      expect(asst.pendingStreamFinalize).toBeUndefined();
      expect(asst.finishReason).toBe("tool_calls");
    }
  });

  it("assistant_done stamps reasoning_elapsed_ms when episode start and clock are provided", () => {
    let blocks: LiveBlock[] = [];
    blocks = applyStreamEvent(
      blocks,
      { type: "phase", phase: "model", round: 0 },
      ctx,
    );
    blocks = applyStreamEvent(
      blocks,
      { type: "reasoning_delta", text: "plan" },
      ctx,
    );
    blocks = applyStreamEvent(
      blocks,
      { type: "assistant_done", finish_reason: "stop" },
      {
        assistantStreamPhase: "model",
        thinkingEpisodeStartedAtMs: 1_000,
        assistantDoneClockMs: 29_000,
      },
    );
    const asst = blocks.find((b) => b.kind === "assistant");
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.reasoning_elapsed_ms).toBe(28_000);
    }
  });

  it("confirmationFooterIconsFromOutcomes shows pending when not all resolved", () => {
    expect(confirmationFooterIconsFromOutcomes(["a"], {})).toEqual(["pending"]);
    expect(
      confirmationFooterIconsFromOutcomes(["a", "b"], { a: true }),
    ).toEqual(["approved", "pending"]);
  });

  it("confirmationFooterIconsFromOutcomes returns empty when all resolved (tool cards show icons)", () => {
    expect(confirmationFooterIconsFromOutcomes(["a"], { a: true })).toEqual([]);
    expect(confirmationFooterIconsFromOutcomes(["a"], { a: false })).toEqual(
      [],
    );
    expect(
      confirmationFooterIconsFromOutcomes(["a", "b"], { a: true, b: true }),
    ).toEqual([]);
    expect(
      confirmationFooterIconsFromOutcomes(["a", "b"], { a: true, b: false }),
    ).toEqual([]);
  });

  it("confirmationFooterIconsFromOutcomes uses single approved for empty pending-id list", () => {
    expect(confirmationFooterIconsFromOutcomes([], { a: true })).toEqual([
      "approved",
    ]);
  });

  it("compactBlocksForHistory clears streaming flags on flushed assistant rows", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "assistant",
        id: "a1",
        text: "Hello.",
        streaming: true,
        streamPhase: "summary",
      },
    ];
    const out = compactBlocksForHistory(blocks);
    const asst = out.find((b) => b.kind === "assistant");
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.streaming).toBe(false);
    }
  });

  it("compactBlocksForHistory drops inbox_review_required (no thread status row)", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "assistant",
        id: "a1",
        text: "Hi",
        streaming: false,
        streamPhase: "model",
      },
      {
        kind: "inbox_review_required",
        id: "in1",
        run_id: "r1",
        watches: [],
      },
    ];
    const out = compactBlocksForHistory(blocks);
    expect(out.some((b) => b.kind === "inbox_review_required")).toBe(false);
    expect(out.find((b) => b.kind === "assistant")?.id).toBe("a1");
  });

  it("final clears pendingStreamFinalize if assistant_done never arrived", () => {
    let blocks: LiveBlock[] = [];
    blocks = applyStreamEvent(
      blocks,
      { type: "phase", phase: "model", round: 0 },
      ctx,
    );
    blocks = applyStreamEvent(blocks, { type: "assistant_delta", text: "Hi" }, ctx);
    blocks = applyStreamEvent(
      blocks,
      {
        type: "tool_call",
        name: "x",
        arguments: "{}",
        cli_line: "hof fn x",
      },
      ctx,
    );
    blocks = applyStreamEvent(blocks, { type: "final" }, ctx);

    const asst = blocks.find((b) => b.kind === "assistant");
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.pendingStreamFinalize).toBeUndefined();
    }
  });

  it("finalizeLiveBlocksAfterUserStop keeps partial text and stamps cancelled", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "assistant",
        id: "a1",
        text: "Partial reply…",
        streaming: true,
        streamPhase: "model",
      },
    ];
    const out = finalizeLiveBlocksAfterUserStop(blocks);
    expect(out.length).toBe(1);
    const asst = out[0];
    expect(asst?.kind).toBe("assistant");
    if (asst?.kind === "assistant") {
      expect(asst.streaming).toBe(false);
      expect(asst.text).toBe("Partial reply…");
      expect(asst.finishReason).toBe("cancelled");
    }
  });

  it("finalizeLiveBlocksAfterUserStop keeps tool_call rows", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "tool_call",
        id: "t1",
        name: "list_expenses",
        cli_line: "hof fn list_expenses",
        arguments: "{}",
      },
    ];
    const out = finalizeLiveBlocksAfterUserStop(blocks);
    expect(out.some((b) => b.kind === "tool_call")).toBe(true);
  });

  it("finalizeLiveBlocksAfterUserStop drops empty cancelled shell", () => {
    const blocks: LiveBlock[] = [
      {
        kind: "assistant",
        id: "a1",
        text: "",
        streaming: true,
        streamPhase: "model",
      },
    ];
    const out = finalizeLiveBlocksAfterUserStop(blocks);
    expect(out.filter((b) => b.kind === "assistant").length).toBe(0);
  });
});

describe("finalizePlanFromTerminalEvent", () => {
  it("uses server plan_run_id when present", () => {
    const r = finalizePlanFromTerminalEvent(
      {
        type: "final",
        mode: "plan",
        plan_run_id: "server-plan-uuid-1",
        structured_plan: {
          title: "T",
          description: "",
          steps: [{ label: "S" }],
        },
      },
      [],
    );
    expect(r.planRunId).toBe("server-plan-uuid-1");
    expect(r.planText).toContain("# T");
  });

  it("falls back to a new id when plan_run_id is missing", () => {
    const r = finalizePlanFromTerminalEvent(
      {
        type: "final",
        mode: "plan",
        structured_plan: {
          title: "T",
          description: "",
          steps: [{ label: "S" }],
        },
      },
      [],
    );
    expect(r.planRunId.length).toBeGreaterThan(8);
  });
});

describe("inferAssistantUiLane (tool_calls turns)", () => {
  const base = {
    kind: "assistant" as const,
    id: "a1",
    text: "Hier ist eine kurze Zusammenfassung der Ausgaben. Bevor ich einen Plan erstelle, brauche ich noch Infos.",
    streaming: false,
    streamPhase: "model" as const,
    finishReason: "tool_calls",
    uiLane: "thinking" as const,
  };

  it("infers reply when prose was streamed as content (not Thought)", () => {
    expect(
      inferAssistantUiLane({
        ...base,
        streamTextRole: "content",
      }),
    ).toBe("reply");
  });

  it("infers reply for mixed reasoning+assistant before tools", () => {
    expect(
      inferAssistantUiLane({
        ...base,
        streamTextRole: "mixed",
      }),
    ).toBe("reply");
  });

  it("infers reply when segment stream has a content segment", () => {
    expect(
      inferAssistantUiLane({
        ...base,
        streamTextRole: "reasoning",
        streamSegments: [
          { kind: "reasoning", text: "Short." },
          {
            kind: "content",
            text: "Visible prose before the clarification tool.",
          },
        ],
      }),
    ).toBe("reply");
  });

  it("infers reply for long reasoning-only flat text (prose in reasoning channel)", () => {
    expect(
      inferAssistantUiLane({
        ...base,
        streamTextRole: "reasoning",
        text: `${"x".repeat(80)} before tools`,
      }),
    ).toBe("reply");
  });

  it("keeps thinking for short reasoning-only before tools", () => {
    expect(
      inferAssistantUiLane({
        ...base,
        streamTextRole: "reasoning",
        text: "Short",
      }),
    ).toBe("thinking");
  });
});
