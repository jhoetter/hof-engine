import type { Element, ElementContent, RootContent } from "hast";

/** Flatten HAST to plain text (post-highlight spans included). */
export function hastTextContent(
  node: RootContent | ElementContent | undefined,
): string {
  if (!node) {
    return "";
  }
  if (node.type === "text") {
    return node.value;
  }
  if (node.type === "element") {
    return node.children
      .map((c) => hastTextContent(c as ElementContent))
      .join("");
  }
  return "";
}

function rowFromTr(tr: Element): string[] {
  return tr.children
    .filter(
      (c): c is Element =>
        c.type === "element" &&
        (c.tagName === "th" || c.tagName === "td"),
    )
    .map((cell) => hastTextContent(cell).trim());
}

/**
 * Parse a GFM `<table>` HAST node into a rectangular matrix [header, ...rows].
 * Returns null if empty or ragged (e.g. streaming).
 */
export function hastTableToMatrix(table: Element): string[][] | null {
  if (table.tagName !== "table") {
    return null;
  }
  const rows: string[][] = [];
  for (const child of table.children) {
    if (child.type !== "element") {
      continue;
    }
    if (child.tagName === "tr") {
      rows.push(rowFromTr(child));
      continue;
    }
    if (
      child.tagName === "thead" ||
      child.tagName === "tbody" ||
      child.tagName === "tfoot"
    ) {
      for (const tr of child.children) {
        if (tr.type === "element" && tr.tagName === "tr") {
          rows.push(rowFromTr(tr));
        }
      }
    }
  }
  if (rows.length === 0) {
    return null;
  }
  const width = rows[0]!.length;
  if (width === 0) {
    return null;
  }
  if (!rows.every((r) => r.length === width)) {
    return null;
  }
  return rows;
}

/** Plain source inside `<pre><code>…</code></pre>` (for clipboard). */
export function hastPreCodePlainText(preNode: Element): string {
  if (preNode.tagName !== "pre") {
    return "";
  }
  const code = preNode.children.find(
    (c): c is Element => c.type === "element" && c.tagName === "code",
  );
  if (!code) {
    return hastTextContent(preNode).replace(/\n$/, "");
  }
  return hastTextContent(code).replace(/\n$/, "");
}
