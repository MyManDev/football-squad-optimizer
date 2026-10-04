/**
 * The standing rule, applied to the whole of the site's own words.
 *
 * No member-facing page or payload, in English or Turkish, publishes a modeled probability, a
 * percentage of a probability, a quantile, a spread, a likelihood, a chance or odds. Only
 * expected points, an expected gap against a named rival, overlap counts and a price in
 * points are publishable. The repository's pre-registered attempts to publish rank
 * probabilities failed three times and a stop rule closed the line.
 *
 * Page-level tests already hold the rendered advice, scoreboard and member surfaces inside
 * that envelope. This one walks the source of every word those pages can show: every entry
 * of every catalogue in `testSupport/catalogues.ts`, in both languages, with function-valued
 * entries called so their interpolated form is checked too, not just the entries some page
 * happens to render today; and every string a production component writes inline.
 */

/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { CATALOGUES } from "../testSupport/catalogues";
import { AS_A_CHANCE } from "../testSupport/honesty";
import type { Language } from "./messages";

const LANGUAGES: readonly Language[] = ["en", "tr"];

// No entry is exempt. Two denials once were ("... never a chance of winning." on /moves and
// "... rather than a probability nobody measured." on /rivals); a denial still puts the
// word on the page, so both were rewritten without it.

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
// The site-wide catalogue's paths start at the language. A page-scoped copy module, kept out
// of the first visit's bundle, is walked as if it were here, under its own name.
for (const [name, copy] of Object.entries(CATALOGUES)) {
  for (const language of LANGUAGES) {
    collect(copy[language], name === "messages" ? language : `${language}.${name}`, catalogue);
  }
}

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Production modules under `src`: anything that is not a test, `test/` or `testSupport/`. */
const PRODUCTION = (readdirSync(SRC, { recursive: true }) as string[])
  .map((name) => name.replace(/\\/g, "/"))
  .filter((name) => /\.tsx?$/.test(name) && !name.endsWith(".d.ts"))
  .filter((name) => !/\.(test|spec)\.tsx?$/.test(name))
  .filter((name) => !/(^|\/)(test|testSupport|__tests__)\//.test(name));

describe("every string in both message catalogues", () => {
  it("was actually walked, both languages, strings and called functions alike", () => {
    expect(catalogue.size).toBeGreaterThan(1000);
    expect(catalogue.get("en.squad.squadCost")).toBe("Squad Cost");
    expect(catalogue.get("tr.squad.squadCost")).toBe("Kadro Maliyeti");
    // A function-valued entry, called, not skipped.
    expect(catalogue.get("en.squad.projectedPlayerPoints")).toBe("xP 1");
    expect(catalogue.get("tr.chipCopy.title")).toBe("Çip seçimi");
    expect(catalogue.get("en.chipCopy.chosen")).toBe(
      "1 is played this gameweek because you chose it.",
    );
    for (const path of catalogue.keys()) {
      const twin = path.startsWith("en.") ? `tr.${path.slice(3)}` : `en.${path.slice(3)}`;
      expect(catalogue.has(twin)).toBe(true);
    }
  });

  it("walks every copy module the source holds", () => {
    const modules = PRODUCTION.filter((path) => /(^|\/)[^/]+Copy\.ts$/.test(path)).map((path) =>
      path.replace(/^.*\/|\.ts$/g, ""),
    );
    const registered = Object.keys(CATALOGUES).filter((name) => name !== "messages");
    expect(registered.sort()).toEqual(modules.sort());
  });

  it("publishes no probability, percentage of one, quantile, spread, likelihood or odds", () => {
    const offenders = [...catalogue]
      .filter(([, text]) => AS_A_CHANCE.test(text))
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
  });

  it("words the two former denials without the thing they denied", () => {
    for (const path of [
      "en.decision.diagnosticTitle",
      "tr.decision.diagnosticTitle",
      "en.rivals.noRivalAfterStatus",
      "tr.rivals.noRivalAfterStatus",
    ]) {
      expect(catalogue.get(path)).toBeDefined();
      expect(catalogue.get(path)).not.toMatch(AS_A_CHANCE);
    }
  });

  it("names no raw capture field in a sentence", () => {
    const offenders = [...catalogue]
      .filter(([, text]) => /selected_by_percent/.test(text))
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
    for (const language of LANGUAGES)
      expect(catalogue.has(`${language}.league.ownershipNote`)).toBe(false);
  });

  it("never writes the Top 100 setting as a share, a winner or a gain", () => {
    const top100 = [...catalogue].filter(([path]) => path.includes(".top100Copy."));
    expect(top100.length).toBeGreaterThan(40);
    const offenders = top100
      .filter(([, text]) =>
        /per\s?cent|\bbest\b|optimal|likely|uplift|boost|recommended|\/\s*100|önerilen|en iyi|artış|getiri/i.test(
          text,
        ),
      )
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
  });

  it("never words a chosen chip's gain as a recommendation or names a week to play it", () => {
    const chip = [...catalogue].filter(([path]) => path.includes(".chipCopy."));
    expect(chip.length).toBeGreaterThan(50);
    const offenders = chip
      .filter(([, text]) =>
        /recommend|\bbest\b|optimal|likely|should play|right week|öner|en iyi|en uygun|oynamalısın/i.test(
          text,
        ),
      )
      .map(([path, text]) => `${path}: ${text}`);
    expect(offenders).toEqual([]);
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

/**
 * The words a production component writes inline: every string literal, the text of every
 * template and every piece of JSX text. A module specifier names a file and a `style`
 * attribute holds CSS (`width: "100%"`), so neither is copy and neither is read.
 */
function inlineText(path: string): { at: string; text: string }[] {
  const source = ts.createSourceFile(
    path,
    readFileSync(join(SRC, path), "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const found: { at: string; text: string }[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) return;
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && node.name.text === "style") return;
    if (ts.isStringLiteralLike(node) || ts.isTemplateLiteralToken(node) || ts.isJsxText(node)) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      const text = node.text.trim();
      if (text !== "") found.push({ at: `${path}:${line}`, text });
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

const INLINE = PRODUCTION.filter((path) => path.endsWith(".tsx")).flatMap(inlineText);

// FPL's captured playing value (25, 50, 75) is shown as the source's own figure, "FPL
// playing value: 75/100", under the same label the FPL card uses. It is not worded as a
// chance and carries no percent marker, so it needs no exemption from the guard.

// No inline sentence is exempt from the guard: the scenario bounds of the information
// review and the role explanations carry no chance wording, so nothing needs an exception
// and modeled role probabilities remain internal.
describe("every string a production component writes inline", () => {
  it("needs no exemption for the scenario surfaces", () => {
    for (const path of [
      "features/league/advice/InformationReview.tsx",
      "features/league/advice/RoleForecast.tsx",
    ]) {
      const inline = INLINE.filter(({ at }) => at.startsWith(`${path}:`));
      expect(inline.length).toBeGreaterThan(0);
      expect(inline.filter(({ text }) => AS_A_CHANCE.test(text))).toEqual([]);
    }
  });
  it("names FPL's playing value as the source's figure, with no chance wording or marker", () => {
    const review = INLINE.filter(({ at }) =>
      at.startsWith("features/league/advice/InformationReview.tsx:"),
    );
    expect(review.some(({ text }) => text === "FPL oynama değeri")).toBe(true);
    expect(review.some(({ text }) => text === "FPL playing value")).toBe(true);
    expect(review.filter(({ text }) => text === "%")).toEqual([]);
  });
  it("was actually read: literals, template text and JSX text, in both languages", () => {
    expect(INLINE.length).toBeGreaterThan(1000);
    const texts = new Set(INLINE.map(({ text }) => text));
    expect(texts.has("İki modelin karşılaştırması")).toBe(true);
    expect(texts.has("Aynı kadro, bütçe,")).toBe(true);
    expect(texts.has("SquadOpt")).toBe(true);
  });

  it("publishes no probability, percentage of one, quantile, spread, likelihood or odds", () => {
    const offenders = INLINE.filter(({ text }) => AS_A_CHANCE.test(text)).map(
      ({ at, text }) => `${at}: ${text}`,
    );
    expect(offenders).toEqual([]);
  });
});
