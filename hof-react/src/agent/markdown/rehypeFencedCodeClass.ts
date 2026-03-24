/**
 * Marks `<pre><code>` (fenced markdown blocks) with `hof-md-fenced` so the
 * `code` component can tell them apart from inline `code` without relying on
 * `language-*` (optional on fences) or `hljs` (skipped for unknown langs when
 * detection is off).
 */
import type { Element, Root } from "hast";

const MARK = "hof-md-fenced";

function pushClass(props: Element["properties"]): void {
  if (!props) {
    return;
  }
  const cn = props.className;
  if (Array.isArray(cn)) {
    if (!cn.some((c) => String(c).includes(MARK))) {
      cn.push(MARK);
    }
  } else if (typeof cn === "string") {
    if (!cn.includes(MARK)) {
      props.className = `${cn} ${MARK}`.trim();
    }
  } else {
    props.className = [MARK];
  }
}

function walk(node: Root | Element): void {
  if (node.type === "root") {
    for (const child of node.children) {
      if (child.type === "element") {
        walk(child);
      }
    }
    return;
  }

  if (node.tagName === "pre") {
    const first = node.children[0];
    if (first?.type === "element" && first.tagName === "code") {
      first.properties ??= {};
      pushClass(first.properties);
    }
  }

  for (const child of node.children) {
    if (child.type === "element") {
      walk(child);
    }
  }
}

export function rehypeFencedCodeClass() {
  return function (tree: Root): void {
    walk(tree);
  };
}
