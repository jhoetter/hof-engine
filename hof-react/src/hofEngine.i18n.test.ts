import { describe, expect, it } from "vitest";
import en from "../locales/en/hofEngine.json";
import de from "../locales/de/hofEngine.json";

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function collectLeaves(obj: unknown, prefix: string[] = []): Map<string, string> {
  const out = new Map<string, string>();
  if (typeof obj === "string") {
    out.set(prefix.join("."), obj);
    return out;
  }
  if (Array.isArray(obj)) {
    obj.forEach((item, i) => {
      for (const [k, v] of collectLeaves(item, [...prefix, String(i)])) {
        out.set(k, v);
      }
    });
    return out;
  }
  if (isPlainObject(obj)) {
    for (const [k, v] of Object.entries(obj)) {
      for (const [path, str] of collectLeaves(v, [...prefix, k])) {
        out.set(path, str);
      }
    }
  }
  return out;
}

function missingKeys(a: Set<string>, b: Set<string>): string[] {
  return [...a].filter((k) => !b.has(k)).sort();
}

const PLACEHOLDER_RE = /\{\{([^}]+)\}\}/g;

function placeholdersIn(s: string): string[] {
  const found: string[] = [];
  for (const m of s.matchAll(PLACEHOLDER_RE)) {
    found.push(m[1]!.trim());
  }
  return [...new Set(found)].sort();
}

describe("hofEngine locale files", () => {
  it("has identical key paths in en and de", () => {
    const enLeaves = collectLeaves(en);
    const deLeaves = collectLeaves(de);
    const enKeys = new Set(enLeaves.keys());
    const deKeys = new Set(deLeaves.keys());
    expect({
      missingInDe: missingKeys(enKeys, deKeys),
      missingInEn: missingKeys(deKeys, enKeys),
    }).toEqual({ missingInDe: [], missingInEn: [] });
  });

  it("English leaves are non-empty", () => {
    const bad: string[] = [];
    for (const [path, v] of collectLeaves(en)) {
      if (!v.trim()) bad.push(path);
    }
    expect(bad).toEqual([]);
  });

  it("keeps {{placeholder}} sets aligned between en and de", () => {
    const enLeaves = collectLeaves(en);
    const deLeaves = collectLeaves(de);
    const mismatches: string[] = [];
    for (const path of enLeaves.keys()) {
      const ev = enLeaves.get(path)!;
      const dv = deLeaves.get(path)!;
      const ep = placeholdersIn(ev).join(", ");
      const dp = placeholdersIn(dv).join(", ");
      if (ep !== dp) {
        mismatches.push(`${path}: en [${ep}] vs de [${dp}]`);
      }
    }
    expect(mismatches).toEqual([]);
  });
});
