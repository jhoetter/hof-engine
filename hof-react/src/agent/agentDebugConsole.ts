/** Browser console mirror for agent stream debugging (filter DevTools by `hof-agent-debug`). */
export function hofAgentConsoleDebug(
  hypothesisId: string,
  location: string,
  message: string,
  data: Record<string, unknown>,
): void {
  try {
    if (
      typeof process !== "undefined" &&
      process.env.NODE_ENV === "test"
    ) {
      return;
    }
    if (typeof console === "undefined" || typeof console.debug !== "function") {
      return;
    }
    console.debug(`[hof-agent-debug:${hypothesisId}] ${message}`, {
      location,
      ...data,
      t: Date.now(),
    });
  } catch {
    /* ignore */
  }
}
