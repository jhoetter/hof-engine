import { describe, expect, it } from "vitest";
import {
  applyStreamEvent,
  compactBlocksForHistory,
  confirmationFooterFromOutcomes,
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

  it("confirmationFooterFromOutcomes is silent once all choices are known", () => {
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
});
