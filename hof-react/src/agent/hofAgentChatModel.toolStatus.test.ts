import { describe, expect, it } from "vitest";
import { toolGroupAggregatedStatus, toolResultUiStatus } from "./hofAgentChatModel";

describe("toolGroupAggregatedStatus", () => {
  it("maps lifecycle and stream fields to compact labels", () => {
    expect(toolGroupAggregatedStatus(undefined, true)).toEqual({
      label: "running",
      tone: "running",
    });
    expect(toolGroupAggregatedStatus(undefined, false)).toEqual({
      label: "error",
      tone: "error",
    });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "w",
          pending_confirmation: true,
          status_code: 202,
        },
        false,
        true,
      ),
    ).toEqual({ label: "done", tone: "success" });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "w",
          pending_confirmation: true,
          status_code: 202,
        },
        false,
        false,
      ),
    ).toEqual({ label: "rejected", tone: "error" });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "w",
          pending_confirmation: true,
          status_code: 202,
        },
        false,
      ),
    ).toEqual({ label: "pending", tone: "pending" });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "ok",
          ok: true,
          status_code: 200,
        },
        false,
      ),
    ).toEqual({ label: "done", tone: "success" });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "bad",
          ok: false,
          status_code: 500,
        },
        false,
      ),
    ).toEqual({ label: "failed", tone: "error" });
    expect(
      toolGroupAggregatedStatus(
        {
          kind: "tool_result",
          id: "x",
          name: "n",
          summary: "rej",
          ok: false,
          status_code: 499,
        },
        false,
      ),
    ).toEqual({ label: "rejected", tone: "error" });
  });
});

describe("toolResultUiStatus", () => {
  it("uses rejection headline for 499", () => {
    expect(
      toolResultUiStatus({
        summary: "rejected",
        ok: false,
        status_code: 499,
      }),
    ).toMatchObject({
      code: 499,
      headline: "You rejected this action",
      tone: "error",
    });
  });

  it("uses stream fields when present", () => {
    expect(
      toolResultUiStatus({
        summary: "ok",
        ok: true,
        status_code: 200,
      }),
    ).toEqual({
      code: 200,
      label: "OK",
      tone: "success",
      headline: "Succeeded",
    });
    expect(
      toolResultUiStatus({
        summary: "bad",
        ok: false,
        status_code: 422,
      }),
    ).toEqual({
      code: 422,
      label: "Validation error",
      tone: "error",
      headline: "Failed",
    });
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
      headline: "Waiting for your approval",
      detail:
        "The mutation has not run yet. Approve or reject on the pending tool row; the assistant continues when every pending action has a choice.",
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
    expect(st.headline).toBe("Waiting for your approval");
    expect(st.detail).toContain("Manager review");
    expect(st.detail).toContain("pending tool row");
  });

  it("infers error from data or summary when stream omits codes", () => {
    expect(
      toolResultUiStatus({
        summary: "fine",
        data: { error: "nope" },
      }),
    ).toEqual({
      code: 502,
      label: "Tool error",
      tone: "error",
      headline: "Failed",
    });
    expect(
      toolResultUiStatus({
        summary: "error: something failed",
      }),
    ).toEqual({
      code: 502,
      label: "Error",
      tone: "error",
      headline: "Failed",
    });
  });
});
