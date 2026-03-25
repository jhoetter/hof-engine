"use client";

import type { Components } from "react-markdown";
import {
  useEffect,
  useMemo,
  type ComponentPropsWithoutRef,
  type MouseEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { CodeFence } from "./markdown/CodeFence";
import { InlineCodeWithCopy } from "./markdown/InlineCodeWithCopy";
import { HLJS_SCOPED_CSS } from "./markdown/hljsTokens";
import { MarkdownSortableTable } from "./markdown/MarkdownSortableTable";
import { prepareAssistantMarkdownSource } from "./markdown/prepareAssistantMarkdownSource";
import { rehypeFencedCodeClass } from "./markdown/rehypeFencedCodeClass";
import { useAssistantMarkdownLinkClick } from "./assistantMarkdownLinkContext";

function MarkdownAnchor({
  href,
  children,
  onClick,
  ...props
}: ComponentPropsWithoutRef<"a">) {
  const intercept = useAssistantMarkdownLinkClick();
  const handleClick = (ev: MouseEvent<HTMLAnchorElement>) => {
    if (typeof href === "string" && intercept && typeof window !== "undefined") {
      const abs = new URL(href, window.location.origin).href;
      intercept(abs, ev);
      if (ev.defaultPrevented) {
        return;
      }
    }
    onClick?.(ev);
  };
  const external = typeof href === "string" && /^https?:\/\//i.test(href);
  return (
    <a
      href={href}
      className="font-medium text-[var(--color-accent)] underline decoration-[var(--color-accent)]/40 underline-offset-2 hover:decoration-[var(--color-accent)]"
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      onClick={handleClick}
      {...props}
    >
      {children}
    </a>
  );
}

/**
 * Streaming can yield ragged GFM tables or half-open fences; sortable table
 * then falls back to the default DOM until the matrix is rectangular.
 */
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
  a: ({ href, children, ...props }) => (
    <MarkdownAnchor href={href} {...props}>
      {children}
    </MarkdownAnchor>
  ),
  code: ({ className, children, node, ...props }) => {
    const cls = typeof className === "string" ? className : "";
    // Fenced blocks may omit `language-*`; hljs may be absent (unknown lang, nohighlight).
    // `hof-md-fenced` is added by rehypeFencedCodeClass on every `<pre><code>` tree.
    const isBlock =
      /\blanguage-[\w-]+\b/.test(cls) ||
      /\bhljs\b/.test(cls) ||
      /\bhof-md-fenced\b/.test(cls);
    if (isBlock) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <InlineCodeWithCopy node={node} className={className} {...props}>
        {children}
      </InlineCodeWithCopy>
    );
  },
  pre: ({ node, children, ...props }) => (
    <CodeFence node={node} {...props}>
      {children}
    </CodeFence>
  ),
  table: ({ node, children }) => (
    <MarkdownSortableTable node={node}>{children}</MarkdownSortableTable>
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
 * Renders assistant Markdown with GFM, `remark-math` + KaTeX (`$…$`, `$$…$$`,
 * or fenced ` ```math `), syntax highlighting (lowlight / hljs), spurious
 * pipe-only text neutralized so it does not become tables, sortable pipe
 * tables when structurally valid, expand-on-hover for tables, and copy on code
 * blocks.
 */
const HLJS_STYLE_ID = "hof-agent-md-hljs-styles";
/** Keep in sync with the `katex` dependency version (for CDN stylesheet). */
const KATEX_CSS_ID = "hof-agent-md-katex-css";
const KATEX_STYLESHEET_HREF =
  "https://cdn.jsdelivr.net/npm/katex@0.16.41/dist/katex.min.css";

export function AssistantMarkdown({ source }: AssistantMarkdownProps) {
  const prepared = useMemo(
    () => prepareAssistantMarkdownSource(source),
    [source],
  );

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    if (document.getElementById(HLJS_STYLE_ID)) {
      return;
    }
    const el = document.createElement("style");
    el.id = HLJS_STYLE_ID;
    el.textContent = HLJS_SCOPED_CSS;
    document.head.appendChild(el);
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    if (document.getElementById(KATEX_CSS_ID)) {
      return;
    }
    const link = document.createElement("link");
    link.id = KATEX_CSS_ID;
    link.rel = "stylesheet";
    link.href = KATEX_STYLESHEET_HREF;
    document.head.appendChild(link);
  }, []);

  return (
    <div className="hof-agent-md min-w-0 break-words [&_*]:max-w-full [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto">
      <ReactMarkdown
        remarkPlugins={[remarkMath, remarkGfm]}
        rehypePlugins={[rehypeKatex, rehypeHighlight, rehypeFencedCodeClass]}
        components={mdComponents}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
