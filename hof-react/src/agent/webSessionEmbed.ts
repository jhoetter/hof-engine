const WEB_SESSIONS_PATH = "/web-sessions";

/**
 * Same-origin deep links to the web session canvas (`?id=` required):
 * `/web-sessions?id=…` — used by the assistant to open the embed / aside.
 */
export function isAssistantWebSessionEmbedLink(absHref: string): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const u = new URL(absHref);
    if (u.origin !== window.location.origin) {
      return false;
    }
    const path = u.pathname.replace(/\/$/, "") || "/";
    const id = u.searchParams.get("id")?.trim();
    if (!id) {
      return false;
    }
    return path === WEB_SESSIONS_PATH;
  } catch {
    return false;
  }
}

/** Canonical iframe URL with embed flag for chat-adjacent panels. */
export function toWebSessionEmbedSrc(absHref: string): string {
  const u = new URL(
    absHref,
    typeof window !== "undefined" ? window.location.origin : "http://localhost",
  );
  u.searchParams.set("hof_chat_embed", "1");
  return `${u.pathname}${u.search}`;
}
