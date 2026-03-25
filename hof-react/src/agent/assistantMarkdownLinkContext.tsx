"use client";

import {
  createContext,
  useContext,
  type MouseEvent,
  type ReactNode,
} from "react";

/** Invoked before default navigation; call `preventDefault` to handle the link in-app (e.g. iframe embed). */
export type AssistantMarkdownLinkClickHandler = (
  absHref: string,
  ev: MouseEvent<HTMLAnchorElement>,
) => void;

const AssistantMarkdownLinkClickContext =
  createContext<AssistantMarkdownLinkClickHandler | null>(null);

export function AssistantMarkdownLinkProvider({
  onAssistantMarkdownLinkClick,
  children,
}: {
  onAssistantMarkdownLinkClick?: AssistantMarkdownLinkClickHandler | null;
  children: ReactNode;
}) {
  return (
    <AssistantMarkdownLinkClickContext.Provider
      value={onAssistantMarkdownLinkClick ?? null}
    >
      {children}
    </AssistantMarkdownLinkClickContext.Provider>
  );
}

export function useAssistantMarkdownLinkClick(): AssistantMarkdownLinkClickHandler | null {
  return useContext(AssistantMarkdownLinkClickContext);
}
