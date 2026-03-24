/**
 * GET /api/agent/tools — same auth as {@link streamHofFunction}.
 */

export type AgentToolInfo = {
  name: string;
  mutation: boolean;
  /** One-line summary from function metadata (may be empty). */
  tool_summary: string;
  /** Docstring / long description (may be empty). */
  description: string;
  when_to_use: string;
  when_not_to_use: string;
  related_tools: string[];
  parameters: unknown;
};

export type AgentToolsResponse = {
  configured: boolean;
  tools: AgentToolInfo[];
};

export async function fetchAgentTools(): Promise<AgentToolsResponse> {
  const token =
    typeof localStorage !== "undefined" ? localStorage.getItem("hof_token") : null;
  const res = await fetch("/api/agent/tools", {
    method: "GET",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ detail: res.statusText }))) as {
      detail?: string;
    };
    throw new Error(typeof err.detail === "string" ? err.detail : res.statusText);
  }

  const data = (await res.json()) as unknown;
  if (!data || typeof data !== "object") {
    throw new Error("Invalid response");
  }
  const o = data as Record<string, unknown>;
  const configured = o.configured === true;
  const rawTools = o.tools;
  if (!Array.isArray(rawTools)) {
    throw new Error("Invalid response: tools");
  }
  const tools: AgentToolInfo[] = [];
  for (const item of rawTools) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const t = item as Record<string, unknown>;
    const name = typeof t.name === "string" ? t.name : "";
    if (!name) {
      continue;
    }
    const relatedRaw = t.related_tools;
    const related_tools = Array.isArray(relatedRaw)
      ? relatedRaw.filter((x): x is string => typeof x === "string")
      : [];
    tools.push({
      name,
      mutation: t.mutation === true,
      tool_summary: typeof t.tool_summary === "string" ? t.tool_summary : "",
      description: typeof t.description === "string" ? t.description : "",
      when_to_use: typeof t.when_to_use === "string" ? t.when_to_use : "",
      when_not_to_use: typeof t.when_not_to_use === "string" ? t.when_not_to_use : "",
      related_tools,
      parameters: t.parameters,
    });
  }
  return { configured, tools };
}
