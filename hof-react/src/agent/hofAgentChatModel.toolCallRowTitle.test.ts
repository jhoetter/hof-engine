import { describe, expect, it } from "vitest";
import {
  toolCallRowTitle,
  toolRowContextFromArguments,
} from "./hofAgentChatModel";

describe("toolRowContextFromArguments", () => {
  it("uses display_seq as #n for get_expense", () => {
    expect(
      toolRowContextFromArguments(
        "get_expense",
        JSON.stringify({ display_seq: 3 }),
      ),
    ).toBe("#3");
  });

  it("uses basename of object_key for register_receipt_upload", () => {
    expect(
      toolRowContextFromArguments(
        "register_receipt_upload",
        JSON.stringify({
          object_key: "tenant/acme/uploads/Rechnung_Catering.pdf",
        }),
      ),
    ).toBe("Rechnung_Catering.pdf");
  });

  it("uses id snippet for get_* when no display_seq", () => {
    const id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
    const ctx = toolRowContextFromArguments(
      "get_expense",
      JSON.stringify({ id }),
    );
    expect(ctx).toContain("id ");
    expect(ctx!.length).toBeLessThanOrEqual(20);
  });
});

describe("toolCallRowTitle", () => {
  it("prefixes humanized tool name when displayTitle is filename-only", () => {
    expect(
      toolCallRowTitle({
        name: "register_receipt_upload",
        displayTitle: "Rechnung_Catering.pdf",
      }),
    ).toBe("Register Receipt Upload · Rechnung_Catering.pdf");
  });

  it("keeps a rich model displayTitle as-is", () => {
    expect(
      toolCallRowTitle({
        name: "register_receipt_upload",
        displayTitle: "Registering receipt: Rechnung.pdf",
      }),
    ).toBe("Registering receipt: Rechnung.pdf");
  });

  it("adds argument context when displayTitle is absent", () => {
    expect(
      toolCallRowTitle({
        name: "get_expense",
        arguments: JSON.stringify({ display_seq: 2 }),
      }),
    ).toBe("Get Expense · #2");
  });
});
