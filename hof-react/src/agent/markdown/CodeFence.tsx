"use client";

import type { Element } from "hast";
import { useMemo, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { hastPreCodePlainText } from "./hastTable";
import { CopyCodeButton } from "./CopyCodeButton";

export function CodeFence({
  node,
  children,
  className = "",
  ...preProps
}: ComponentPropsWithoutRef<"pre"> & {
  node?: Element | undefined;
  children?: ReactNode;
}) {
  const plain = useMemo(
    () =>
      node && node.tagName === "pre" ? hastPreCodePlainText(node) : "",
    [node],
  );
  return (
    <div className="group/codefence relative mb-2 last:mb-0">
      {/* Overlay top-right; pointer-events only when visible so text stays selectable */}
      <div
        className="absolute right-1.5 top-1.5 z-10 opacity-0 transition-opacity pointer-events-none group-hover/codefence:pointer-events-auto group-hover/codefence:opacity-100 group-focus-within/codefence:pointer-events-auto group-focus-within/codefence:opacity-100"
      >
        <CopyCodeButton
          text={plain}
          label="Copy code block"
          className="!p-1 shadow-none"
        />
      </div>
      <pre
        className={`max-h-64 overflow-x-auto overflow-y-auto rounded-lg border border-border/60 bg-background/80 p-3 pr-11 font-mono text-[12px] leading-snug text-secondary [&_code]:bg-transparent [&_code]:p-0 ${className}`}
        {...preProps}
      >
        {children}
      </pre>
    </div>
  );
}
