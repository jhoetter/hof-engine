"use client";

import { Maximize2 } from "lucide-react";

export function ExpandTableButton({
  onClick,
  label = "Expand table",
  className = "",
}: {
  onClick: () => void;
  label?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={`inline-flex shrink-0 items-center justify-center rounded-md border border-border/70 bg-background/95 p-1.5 text-secondary shadow-sm transition-colors hover:bg-hover hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-accent)] ${className}`}
    >
      <Maximize2 className="size-3.5" aria-hidden />
    </button>
  );
}
