import { describe, expect, it } from "vitest";
import {
  applyStreamEvent,
  inboxReviewBarrierFromStreamEvent,
  inboxReviewOpenHref,
} from "./hofAgentChatModel";
import type { HofStreamEvent } from "../hooks/streamHofFunction";

describe("awaiting_inbox_review stream handling", () => {
  it("parses barrier from stream event", () => {
    const ev: HofStreamEvent = {
      type: "awaiting_inbox_review",
      run_id: "run-1",
      watches: [
        {
          watch_id: "w1",
          record_type: "expense",
          record_id: "e1",
          label: "Manager review",
          path: "/inbox?id=e1",
        },
      ],
    };
    const b = inboxReviewBarrierFromStreamEvent(ev);
    expect(b).toEqual({
      runId: "run-1",
      watches: [
        {
          watch_id: "w1",
          record_type: "expense",
          record_id: "e1",
          label: "Manager review",
          path: "/inbox?id=e1",
        },
      ],
    });
  });

  it("applyStreamEvent appends inbox_review_required block", () => {
    const ev: HofStreamEvent = {
      type: "awaiting_inbox_review",
      run_id: "r2",
      watches: [
        { watch_id: "a", record_type: "revenue", record_id: "rv1" },
      ],
    };
    const next = applyStreamEvent([], ev, {
      assistantStreamPhase: null,
      thinkingEpisodeStartedAtMs: null,
    });
    const row = next.find((x) => x.kind === "inbox_review_required");
    expect(row?.kind).toBe("inbox_review_required");
    if (row?.kind === "inbox_review_required") {
      expect(row.run_id).toBe("r2");
      expect(row.watches).toHaveLength(1);
      expect(row.watches[0].watch_id).toBe("a");
    }
  });

  it("inboxReviewOpenHref prefers url over path", () => {
    expect(
      inboxReviewOpenHref({
        watch_id: "w",
        record_type: "expense",
        record_id: "x",
        url: "https://example.com/inbox",
        path: "/inbox",
      }),
    ).toBe("https://example.com/inbox");
    expect(
      inboxReviewOpenHref({
        watch_id: "w",
        record_type: "expense",
        record_id: "x",
        path: "/inbox?id=1",
      }),
    ).toBe("/inbox?id=1");
  });
});
