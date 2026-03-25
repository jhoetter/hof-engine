import { describe, expect, it } from "vitest";
import { barrierMatchesApprovalBlock } from "./hofAgentChatModel";

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
