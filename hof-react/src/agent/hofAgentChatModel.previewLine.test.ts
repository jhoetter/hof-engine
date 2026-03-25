import { describe, expect, it } from "vitest";
import {
  formatPendingPreviewLine,
  postApplyReviewFromPreview,
} from "./hofAgentChatModel";

describe("formatPendingPreviewLine", () => {
  it("uses envelope summary when present", () => {
    expect(
      formatPendingPreviewLine({
        summary: "€100.00 · Auto-approved",
        data: { amount: 100, note: "ignored for line" },
      }),
    ).toBe("€100.00 · Auto-approved");
  });

  it("falls back to note on legacy flat objects", () => {
    expect(
      formatPendingPreviewLine({ note: "Hello world", other: 1 }),
    ).toBe("Hello world");
  });

  it("stringifies object without summary or note", () => {
    expect(formatPendingPreviewLine({ a: 1 })).toBe('{"a":1}');
  });

  it("handles empty", () => {
    expect(formatPendingPreviewLine(null)).toBe("");
    expect(formatPendingPreviewLine(undefined)).toBe("");
  });
});

describe("postApplyReviewFromPreview", () => {
  it("returns href and label from post_apply_review", () => {
    expect(
      postApplyReviewFromPreview({
        summary: "x",
        post_apply_review: {
          label: "Manager review",
          url: "http://example.com/inbox",
          path: "/inbox",
        },
      }),
    ).toEqual({
      href: "http://example.com/inbox",
      label: "Manager review",
      path: "/inbox",
    });
  });

  it("returns relative href from path only", () => {
    expect(
      postApplyReviewFromPreview({
        post_apply_review: { label: "Legal", path: "/compliance" },
      }),
    ).toEqual({
      href: "/compliance",
      label: "Legal",
      path: "/compliance",
    });
  });

  it("returns null when missing or unlabeled", () => {
    expect(postApplyReviewFromPreview(null)).toBeNull();
    expect(postApplyReviewFromPreview({ amount: 1 })).toBeNull();
    expect(
      postApplyReviewFromPreview({ post_apply_review: { path: "/x" } }),
    ).toBeNull();
  });
});
