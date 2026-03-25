import { describe, expect, it } from "vitest";
import {
  barrierMatchesAnyThreadOrLiveBlocks,
  barrierMatchesApprovalBlock,
  type LiveBlock,
  type ThreadItem,
} from "./hofAgentChatModel";

describe("barrierMatchesApprovalBlock", () => {
  const barrier = (runId: string, ids: string[]) => ({
    runId,
    items: ids.map((pendingId) => ({
      pendingId,
      name: "x",
      cli_line: "",
    })),
  });

  it("matches on equal run_id", () => {
    expect(
      barrierMatchesApprovalBlock(
        barrier("run-1", ["a"]),
        "run-1",
        ["b", "c"],
      ),
    ).toBe(true);
  });

  it("matches when pending id sets are identical", () => {
    expect(
      barrierMatchesApprovalBlock(barrier("", ["a", "b"]), "", ["a", "b"]),
    ).toBe(true);
  });

  it("matches when block lists a superset of barrier ids (subset barrier)", () => {
    expect(
      barrierMatchesApprovalBlock(barrier("", ["p2"]), "", ["p1", "p2"]),
    ).toBe(true);
  });

  it("rejects when barrier has an id not in the block", () => {
    expect(
      barrierMatchesApprovalBlock(barrier("", ["p1", "p2"]), "", ["p1"]),
    ).toBe(false);
  });

  it("rejects when run_id differs and sets mismatch", () => {
    expect(
      barrierMatchesApprovalBlock(barrier("r1", ["a"]), "r2", ["b"]),
    ).toBe(false);
  });
});

describe("barrierMatchesAnyThreadOrLiveBlocks", () => {
  const br = {
    runId: "r1",
    items: [{ pendingId: "pid-1", name: "create_expense", cli_line: "" }],
  };

  it("is true when liveBlocks has matching mutation_pending", () => {
    const live: LiveBlock[] = [
      {
        kind: "mutation_pending",
        id: "m1",
        pending_id: "pid-1",
        name: "create_expense",
        cli_line: "hof fn create_expense {}",
      },
    ];
    expect(barrierMatchesAnyThreadOrLiveBlocks(br, [], live)).toBe(true);
  });

  it("is true when a thread run has matching mutation_pending", () => {
    const thread: ThreadItem[] = [
      {
        kind: "run",
        id: "run1",
        blocks: [
          {
            kind: "mutation_pending",
            id: "m1",
            pending_id: "pid-1",
            name: "create_expense",
            cli_line: "",
          } as LiveBlock,
        ],
      },
    ];
    expect(barrierMatchesAnyThreadOrLiveBlocks(br, thread, [])).toBe(true);
  });

  it("is false when no block references barrier pending ids", () => {
    expect(barrierMatchesAnyThreadOrLiveBlocks(br, [], [])).toBe(false);
    const live: LiveBlock[] = [
      {
        kind: "mutation_pending",
        id: "m1",
        pending_id: "other",
        name: "create_expense",
        cli_line: "",
      },
    ];
    expect(barrierMatchesAnyThreadOrLiveBlocks(br, [], live)).toBe(false);
  });

  it("is false for null barrier", () => {
    expect(barrierMatchesAnyThreadOrLiveBlocks(null, [], [])).toBe(false);
  });
});
