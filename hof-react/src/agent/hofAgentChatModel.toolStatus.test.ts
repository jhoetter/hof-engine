import { describe, expect, it } from "vitest";
import { toolResultUiStatus } from "./hofAgentChatModel";

describe("toolResultUiStatus", () => {
  it("uses stream fields when present", () => {
    expect(
      toolResultUiStatus({
        summary: "ok",
        ok: true,
        status_code: 200,
      }),
    ).toEqual({ code: 200, label: "OK", tone: "success" });
    expect(
      toolResultUiStatus({
        summary: "bad",
        ok: false,
        status_code: 422,
      }),
    ).toEqual({ code: 422, label: "Validation error", tone: "error" });
  });

  it("marks pending confirmation with apply-first copy", () => {
    expect(
      toolResultUiStatus({
        summary: "wait",
        pending_confirmation: true,
        status_code: 202,
      }),
    ).toEqual({
      code: 202,
      label: "Confirm below to apply",
      tone: "pending",
      detail:
        "The mutation has not run yet. Approve or reject in Pending actions, then Apply choices.",
    });
  });

  it("pending + post_apply_review explains chat vs post-apply step", () => {
    const st = toolResultUiStatus({
      summary: "wait",
      pending_confirmation: true,
      status_code: 202,
      data: {
        summary: "€1.00 · Pending Review",
        data: { amount: 1, approval_status: "pending_review" },
        post_apply_review: {
          label: "Manager review",
          url: "http://localhost:8001/inbox",
          path: "/inbox",
        },
      },
    });
    expect(st.code).toBe(202);
    expect(st.label).toBe("Confirm in chat first");
    expect(st.detail).toContain("Manager review");
    expect(st.detail).toContain("Pending actions");
  });

  it("infers error from data or summary when stream omits codes", () => {
    expect(
      toolResultUiStatus({
        summary: "fine",
        data: { error: "nope" },
      }),
    ).toEqual({ code: 502, label: "Tool error", tone: "error" });
    expect(
      toolResultUiStatus({
        summary: "error: something failed",
      }),
    ).toEqual({ code: 502, label: "Error", tone: "error" });
  });
});
