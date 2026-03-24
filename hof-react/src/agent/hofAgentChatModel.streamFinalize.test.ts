import { describe, expect, it } from "vitest";
import {
  applyStreamEvent,
  compactBlocksForHistory,
  confirmationFooterFromOutcomes,
  finalizeLiveBlocksAfterUserStop,
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

  it("confirmationFooterFromOutcomes is silent once all choices are known", () => {
    expect(confirmationFooterFromOutcomes(["a"], {})).toBeNull();
    expect(
      confirmationFooterFromOutcomes(["a"], { a: true }),
    ).toBeNull();
    expect(
      confirmationFooterFromOutcomes(["a"], { a: false }),
    ).toBeNull();
    expect(
      confirmationFooterFromOutcomes(["a", "b"], { a: true, b: true }),
    ).toBeNull();
    expect(
      confirmationFooterFromOutcomes(["a", "b"], { a: true, b: false }),
    ).toContain("approved");
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
