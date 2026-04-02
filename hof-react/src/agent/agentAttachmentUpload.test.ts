import { describe, expect, it } from "vitest";
import {
  attachmentKindShortLabel,
  resolveAgentChatAttachmentContentType,
  AGENT_CHAT_ATTACHMENT_MIME_TYPES,
} from "./agentAttachmentUpload";

function file(name: string, type: string): File {
  return new File([""], name, { type });
}

describe("resolveAgentChatAttachmentContentType", () => {
  it("accepts PDF by MIME or extension", () => {
    expect(resolveAgentChatAttachmentContentType(file("a.pdf", "application/pdf"))).toBe(
      "application/pdf",
    );
    expect(resolveAgentChatAttachmentContentType(file("a.pdf", ""))).toBe("application/pdf");
    expect(
      resolveAgentChatAttachmentContentType(file("a.pdf", "application/octet-stream")),
    ).toBe("application/pdf");
  });

  it("accepts Excel and Word Office Open XML", () => {
    expect(
      resolveAgentChatAttachmentContentType(
        file(
          "sheet.xlsx",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
      ),
    ).toBe("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
    expect(resolveAgentChatAttachmentContentType(file("sheet.xlsx", ""))).toBe(
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    );
    expect(
      resolveAgentChatAttachmentContentType(
        file(
          "memo.docx",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
      ),
    ).toBe("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  });

  it("rejects unknown extensions", () => {
    expect(resolveAgentChatAttachmentContentType(file("a.exe", "application/octet-stream"))).toBeNull();
    expect(resolveAgentChatAttachmentContentType(file("a.bin", ""))).toBeNull();
  });

  it("AGENT_CHAT_ATTACHMENT_MIME_TYPES stays non-empty", () => {
    expect(AGENT_CHAT_ATTACHMENT_MIME_TYPES.length).toBeGreaterThan(3);
  });
});

describe("attachmentKindShortLabel", () => {
  it("maps common MIME types", () => {
    expect(attachmentKindShortLabel("application/pdf")).toBe("PDF");
    expect(
      attachmentKindShortLabel(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ),
    ).toBe("XLSX");
    expect(
      attachmentKindShortLabel(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ),
    ).toBe("DOCX");
    expect(attachmentKindShortLabel("text/csv")).toBe("CSV");
    expect(attachmentKindShortLabel("text/plain")).toBe("TXT");
  });

  it("falls back to filename extension", () => {
    expect(attachmentKindShortLabel("", "report.xlsx")).toBe("XLSX");
    expect(attachmentKindShortLabel("application/octet-stream", "a.json")).toBe("JSON");
  });

  it("returns FILE when unknown", () => {
    expect(attachmentKindShortLabel("", "")).toBe("FILE");
    expect(attachmentKindShortLabel("application/unknown", "noext")).toBe("FILE");
  });
});
