/**
 * Agent chat file attachments: allowed MIME types must stay in sync with backend
 * `presign_unstructured_upload` (e.g. spreadsheet-app `functions/unstructured_ingest.py`).
 */

export const AGENT_CHAT_ATTACHMENT_MIME_TYPES = [
  "application/pdf",
  "text/plain",
  "text/csv",
  "text/tab-separated-values",
  "text/markdown",
  "text/html",
  "application/json",
  "application/xml",
  "text/xml",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
] as const;

const _ALLOWED = new Set<string>(AGENT_CHAT_ATTACHMENT_MIME_TYPES);

/** Lowercase extension → canonical MIME (for empty or generic browser `file.type`). */
const EXT_TO_MIME: Record<string, string> = {
  ".pdf": "application/pdf",
  ".txt": "text/plain",
  ".text": "text/plain",
  ".csv": "text/csv",
  ".tsv": "text/tab-separated-values",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".html": "text/html",
  ".htm": "text/html",
  ".json": "application/json",
  ".xml": "application/xml",
  ".xlsx":
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".docx":
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

/**
 * `<input type="file" accept="…">` — MIME tokens plus extensions so the picker
 * filters reliably across browsers (some only honor extensions).
 */
export const AGENT_CHAT_ATTACHMENT_ACCEPT = [
  ...AGENT_CHAT_ATTACHMENT_MIME_TYPES,
  ".pdf",
  ".txt",
  ".text",
  ".csv",
  ".tsv",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".json",
  ".xml",
  ".xlsx",
  ".docx",
].join(",");

function normalizeMime(raw: string): string {
  return raw.trim().toLowerCase().split(";")[0].trim();
}

/**
 * Returns a canonical `Content-Type` for S3 presign + PUT, or `null` if the file
 * is not an allowed document type.
 */
export function resolveAgentChatAttachmentContentType(file: File): string | null {
  const name = file.name.trim().toLowerCase();
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot) : "";
  const fromExt = ext ? EXT_TO_MIME[ext] : undefined;
  const reported = normalizeMime(file.type || "");

  if (reported && _ALLOWED.has(reported)) {
    return reported;
  }
  if (
    (!reported ||
      reported === "application/octet-stream" ||
      reported === "binary/octet-stream") &&
    fromExt
  ) {
    return fromExt;
  }
  if (fromExt && _ALLOWED.has(fromExt)) {
    return fromExt;
  }
  return null;
}

/**
 * Short uppercase label for attachment chips (thread UI), from MIME and optional filename.
 */
export function attachmentKindShortLabel(
  contentType: string,
  filename?: string,
): string {
  const ct = (contentType || "").trim().toLowerCase().split(";")[0].trim();
  if (ct) {
    if (ct.includes("pdf")) {
      return "PDF";
    }
    if (ct.includes("spreadsheetml.sheet")) {
      return "XLSX";
    }
    if (ct.includes("wordprocessingml.document")) {
      return "DOCX";
    }
    if (ct === "text/csv") {
      return "CSV";
    }
    if (ct === "text/tab-separated-values") {
      return "TSV";
    }
    if (ct === "text/plain") {
      return "TXT";
    }
    if (ct === "text/markdown") {
      return "MD";
    }
    if (ct === "text/html") {
      return "HTML";
    }
    if (ct === "application/json") {
      return "JSON";
    }
    if (ct === "application/xml" || ct === "text/xml") {
      return "XML";
    }
  }
  const name = (filename || "").trim().toLowerCase();
  const dot = name.lastIndexOf(".");
  if (dot >= 0 && dot < name.length - 1) {
    const ext = name.slice(dot + 1);
    if (ext && /^[a-z0-9]+$/i.test(ext)) {
      const u = ext.toUpperCase();
      return u.length <= 6 ? u : u.slice(0, 6);
    }
  }
  return "FILE";
}
