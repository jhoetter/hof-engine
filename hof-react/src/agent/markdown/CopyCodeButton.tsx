"use client";

import { Check, Copy } from "lucide-react";
import { useCallback, useState } from "react";

export function CopyCodeButton({
  text,
  label = "Copy code",
  className = "",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  const onClick = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
      window.setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      window.setTimeout(() => setState("idle"), 2000);
    }
  }, [text]);

  const title =
    state === "copied"
      ? "Copied"
      : state === "error"
        ? "Copy failed"
        : label;

  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={`inline-flex shrink-0 items-center justify-center rounded-md border border-border/70 bg-background/95 p-1.5 text-secondary shadow-sm transition-colors hover:bg-hover hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-accent)] ${className}`}
    >
      {state === "copied" ? (
        <Check className="size-3.5 text-[var(--color-accent)]" aria-hidden />
      ) : (
        <Copy className="size-3.5" aria-hidden />
      )}
    </button>
  );
}
