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
    <span className="group/inlinecode inline-flex max-w-full items-center gap-0.5 align-middle">
      <code
        className={`rounded border border-border/60 bg-background/90 px-1 py-0.5 font-mono text-[12px] text-foreground ${className}`}
        {...props}
      >
        {children}
      </code>
      {text ? (
        <CopyCodeButton
          text={text}
          label="Copy inline code"
          className="!p-1 opacity-0 transition-opacity focus-visible:opacity-100 group-hover/inlinecode:opacity-100 group-focus-within/inlinecode:opacity-100"
        />
      ) : null}
    </span>
  );
}
