"use client";

import {
  createContext,
  useContext,
  type ReactNode,
} from "react";

export type AssistantMarkdownTableRendererContext = {
  headers: string[];
  rows: string[][];
};

export type AssistantMarkdownTableRenderer = (
  ctx: AssistantMarkdownTableRendererContext,
) => ReactNode | null;

const AssistantMarkdownTableContext =
  createContext<AssistantMarkdownTableRenderer | null>(null);

export function AssistantMarkdownTableProvider({
  renderer,
  children,
}: {
  renderer?: AssistantMarkdownTableRenderer;
  children: ReactNode;
}) {
  return (
    <AssistantMarkdownTableContext.Provider value={renderer ?? null}>
      {children}
    </AssistantMarkdownTableContext.Provider>
  );
}

export function useAssistantMarkdownTableRenderer(): AssistantMarkdownTableRenderer | null {
  return useContext(AssistantMarkdownTableContext);
}
