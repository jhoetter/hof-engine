"use client";

import type { Element } from "hast";
import { useMemo, type ComponentPropsWithoutRef } from "react";
import { hastTextContent } from "./hastTable";
import { CopyCodeButton } from "./CopyCodeButton";

export function InlineCodeWithCopy({
  node,
  children,
  className = "",
  ...props
}: ComponentPropsWithoutRef<"code"> & { node?: Element | undefined }) {
  const text = useMemo(
    () =>
      node && node.tagName === "code" ? hastTextContent(node).trim() : "",
    [node],
  );

  return (
    <span className="group/inlinecode relative inline max-w-full align-baseline">
      <code
        className={`rounded border border-border/60 bg-background/90 px-1 py-px font-mono text-[12px] leading-snug text-foreground ${className}`}
        {...props}
      >
        {children}
      </code>
      {text ? (
        <CopyCodeButton
          text={text}
          label="Copy inline code"
          className="pointer-events-none absolute left-full top-1/2 z-[1] !ml-0.5 !-translate-y-1/2 !p-1 opacity-0 transition-opacity focus-visible:pointer-events-auto focus-visible:opacity-100 group-hover/inlinecode:pointer-events-auto group-hover/inlinecode:opacity-100 group-focus-within/inlinecode:pointer-events-auto group-focus-within/inlinecode:opacity-100"
        />
      ) : null}
    </span>
  );
}
