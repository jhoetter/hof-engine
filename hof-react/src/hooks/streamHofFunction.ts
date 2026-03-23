/**
 * POST /api/functions/{name}/stream — NDJSON (application/x-ndjson), one JSON object per line.
 */
export type HofStreamEvent = Record<string, unknown> & { type?: string };

export async function streamHofFunction(
  functionName: string,
  params: Record<string, unknown>,
  options: {
    onEvent: (event: HofStreamEvent) => void;
    signal?: AbortSignal;
  },
): Promise<void> {
  const token = typeof localStorage !== "undefined" ? localStorage.getItem("hof_token") : null;
  const res = await fetch(`/api/functions/${functionName}/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(params),
    signal: options.signal,
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: res.statusText }))) as { detail?: string };
    throw new Error(typeof err.detail === "string" ? err.detail : res.statusText);
  }

  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const t = line.trim();
      if (!t) {
        continue;
      }
      try {
        const parsed = JSON.parse(t) as HofStreamEvent;
        options.onEvent(parsed);
      } catch {
        /* ignore malformed line */
      }
    }
  }

  const tail = buffer.trim();
  if (tail) {
    try {
      const parsed = JSON.parse(tail) as HofStreamEvent;
      options.onEvent(parsed);
    } catch {
      /* ignore */
    }
  }
}
