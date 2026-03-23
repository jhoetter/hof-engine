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

  it("marks pending confirmation", () => {
    expect(
      toolResultUiStatus({
        summary: "wait",
        pending_confirmation: true,
        status_code: 202,
      }),
    ).toEqual({ code: 202, label: "Awaiting confirmation", tone: "pending" });
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
