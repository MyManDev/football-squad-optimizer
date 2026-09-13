/**
 * The standing rule, applied to the whole of the site's own words.
 *
 * No member-facing page or payload, in English or Turkish, publishes a probability, a
 * percentage of a probability, a quantile, a spread, a likelihood, a chance or odds. Only
 * expected points, an expected gap against a named rival, overlap counts and a price in
 * points are publishable. The repository's pre-registered attempts to publish rank
 * probabilities failed three times and a stop rule closed the line.
 *
 * Page-level tests already hold the rendered advice, scoreboard and member surfaces inside
 * that envelope. This one walks the source of every word those pages can show: every entry
 * in both catalogues, with function-valued entries called so their interpolated form is
 * checked too, not just the entries some page happens to render today.
 */

import { describe, expect, it } from "vitest";

import { AS_A_CHANCE } from "../testSupport/honesty";
import { MESSAGES, type Language } from "./messages";

const LANGUAGES: readonly Language[] = ["en", "tr"];

/**
 * The only exempt entries, keyed by catalogue path and listed rather than pattern-matched.
 *
 * Both are denials: each tells the reader that the site does not publish a probability, and
 * a denial has to name the thing it refuses in order to refuse it. They are held to that by
 * the second test below, which fails if one of them ever stops matching the guard, so the
 * exemption cannot quietly become cover for a claim.
 *
 *   decision.diagnosticTitle   "... is a diagnostic, never a chance of winning."
 *   rivals.noRivalAfterStatus  "... rather than a probability nobody measured."
 */
const DENIALS: readonly string[] = [
  "en.decision.diagnosticTitle",
  "tr.decision.diagnosticTitle",
  "en.rivals.noRivalAfterStatus",
  "tr.rivals.noRivalAfterStatus",
];

/**
 * Stands in for any argument a message function takes. It answers 1 to every primitive
 * conversion, and itself to every property read and every call, so an entry that
 * interpolates a number, a formatted string, a field of a parameter object or the result of
 * a method on one all produce a checkable sentence.
 */
const placeholder: unknown = new Proxy(function placeholderArgument() {}, {
  get(_target, key) {
    if (key === Symbol.toPrimitive) return () => 1;
    if (key === "toString" || key === "valueOf") return () => 1;
    return placeholder;
  },
  apply: () => placeholder,
});

function collect(node: unknown, path: string, into: Map<string, string>): void {
  if (typeof node === "string" || typeof node === "number" || typeof node === "boolean") {
    into.set(path, String(node));
    return;
  }
  if (typeof node === "function") {
    const call = node as (...args: readonly unknown[]) => unknown;
    const args = Array.from({ length: Math.max(call.length, 1) }, () => placeholder);
    into.set(path, String(call(...args)));
    return;
  }
  if (node !== null && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) collect(value, `${path}.${key}`, into);
  }
}

const catalogue = new Map<string, string>();
for (const language of LANGUAGES) collect(MESSAGES[language], language, catalogue);

describe("every string in both message catalogues", () => {
  it("was actually walked, both languages, strings and called functions alike", () => {
    expect(catalogue.size).toBeGreaterThan(1000);
    expect(catalogue.get("en.squad.squadCost")).toBe("Squad Cost");
    expect(catalogue.get("tr.squad.squadCost")).toBe("Kadro Maliyeti");
    // A function-valued entry, called, not skipped.
    expect(catalogue.get("en.squad.projectedPlayerPoints")).toBe("xP 1");
    for (const path of catalogue.keys()) {
      const twin = path.startsWith("en.") ? `tr.${path.slice(3)}` : `en.${path.slice(3)}`;
      expect(catalogue.has(twin)).toBe(true);
    }
  });

  it("publishes no probability, percentage of one, quantile, spread, likelihood or odds", () => {
    const exempt = new Set(DENIALS);
    const offenders = [...catalogue]
      .filter(([path]) => !exempt.has(path))
      .filter(([, text]) => AS_A_CHANCE.test(text))
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
  });

  it.each(DENIALS)("%s is exempt only because it denies a probability", (path) => {
    const text = catalogue.get(path);
    expect(text).toBeDefined();
    expect(text).toMatch(AS_A_CHANCE);
  });

  it("no longer carries the keys that existed only to label a probability", () => {
    for (const language of LANGUAGES) {
      expect(catalogue.has(`${language}.decision.modes.behind`)).toBe(false);
      expect(catalogue.has(`${language}.decision.modes.aheadFive`)).toBe(false);
      expect(catalogue.has(`${language}.squad.lowerTail`)).toBe(false);
      expect(catalogue.has(`${language}.squad.lowerTailUnavailable`)).toBe(false);
      // The price vocabulary that survives is a cost in points.
      expect(catalogue.has(`${language}.decision.modes.cost`)).toBe(true);
      expect(catalogue.has(`${language}.decision.modes.points`)).toBe(true);
    }
  });
});
