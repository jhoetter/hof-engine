import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { describe, expect, it } from "vitest";

/**
 * Regression: single `$` must not start math (currency / prose), or text is
 * swallowed into KaTeX and spaces collapse. Mirrors {@link AssistantMarkdown}
 * remark/rehype config.
 */
describe("AssistantMarkdown math delimiters", () => {
  function renderMd(markdown: string, singleDollar: boolean): string {
    return renderToStaticMarkup(
      createElement(ReactMarkdown, {
        remarkPlugins: [
          [remarkMath, { singleDollarTextMath: singleDollar }],
          remarkGfm,
        ],
        rehypePlugins: [rehypeKatex],
        children: markdown,
      }),
    );
  }

  it("does not treat currency dollars as math when singleDollarTextMath is off", () => {
    const html = renderMd("**Travel** at $543.50 with an average of $181.17.", false);
    expect(html).not.toContain("katex");
    expect(html).toContain("$543.50");
  });

  it("still renders $$…$$ as math when singleDollarTextMath is off", () => {
    const html = renderMd("Inline $$x^2$$ and done.", false);
    expect(html).toContain("katex");
  });
});
