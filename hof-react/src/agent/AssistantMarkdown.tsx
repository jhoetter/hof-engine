"use client";

import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const mdComponents: Components = {
  p: ({ children, ...props }) => (
    <p className="mb-2 last:mb-0 [&:first-child]:mt-0" {...props}>
      {children}
    </p>
  ),
  h1: ({ children, ...props }) => (
    <h1
      className="mb-2 mt-3 border-b border-border pb-1 text-base font-semibold text-foreground first:mt-0"
      {...props}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2 className="mb-2 mt-3 text-[15px] font-semibold text-foreground first:mt-0" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="mb-1.5 mt-2 text-sm font-semibold text-foreground first:mt-0" {...props}>
      {children}
    </h3>
  ),
  ul: ({ children, ...props }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 text-foreground last:mb-0" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 text-foreground last:mb-0" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="leading-relaxed [&>p]:mb-0" {...props}>
      {children}
    </li>
  ),
  blockquote: ({ children, ...props }) => (
    <blockquote
      className="mb-2 border-l-2 border-border pl-3 text-secondary last:mb-0"
      {...props}
    >
      {children}
    </blockquote>
  ),
  hr: (props) => <hr className="my-3 border-border" {...props} />,
  a: ({ href, children, ...props }) => {
    const external =
      typeof href === "string" && /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        className="font-medium text-[var(--color-accent)] underline decoration-[var(--color-accent)]/40 underline-offset-2 hover:decoration-[var(--color-accent)]"
        {...(external
          ? { target: "_blank", rel: "noopener noreferrer" }
          : {})}
        {...props}
      >
        {children}
      </a>
    );
  },
  code: ({ className, children, ...props }) => {
    const isBlock = /language-[\w-]+/.test(className ?? "");
    if (isBlock) {
      return (
        <code
          className={`font-mono text-[12px] leading-snug text-foreground ${className ?? ""}`}
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded border border-border/60 bg-background/90 px-1 py-0.5 font-mono text-[12px] text-foreground"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }) => (
    <pre
      className="mb-2 max-h-64 overflow-x-auto overflow-y-auto rounded-lg border border-border/60 bg-background/80 p-3 font-mono text-[12px] leading-snug text-secondary last:mb-0"
      {...props}
    >
      {children}
    </pre>
  ),
  table: ({ children, ...props }) => (
    <div className="mb-2 max-w-full overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-left text-[12px] text-foreground" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="border-b border-border bg-surface/40" {...props}>
      {children}
    </thead>
  ),
  tbody: ({ children, ...props }) => <tbody {...props}>{children}</tbody>,
  tr: ({ children, ...props }) => (
    <tr className="border-b border-border/60 last:border-0" {...props}>
      {children}
    </tr>
  ),
  th: ({ children, ...props }) => (
    <th className="px-2 py-1.5 font-semibold text-foreground" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="px-2 py-1.5 align-top text-secondary" {...props}>
      {children}
    </td>
  ),
  strong: ({ children, ...props }) => (
    <strong className="font-semibold text-foreground" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }) => (
    <em className="italic text-foreground" {...props}>
      {children}
    </em>
  ),
};

export type AssistantMarkdownProps = {
  /** Raw Markdown source from the assistant. */
  source: string;
};

/**
 * Renders assistant Markdown with GFM (tables, strikethrough, task lists, etc.).
 * No raw HTML — safe for model-generated text.
 */
export function AssistantMarkdown({ source }: AssistantMarkdownProps) {
  return (
    <div className="hof-agent-md min-w-0 break-words [&_*]:max-w-full">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {source}
      </ReactMarkdown>
    </div>
  );
}
