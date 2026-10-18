/**
 * #1136's motion rules, checked once and centrally:
 *
 * - every duration is a `--motion-*` token of tokens.css, inside the range #1136 sets, and
 *   motion.ts mirrors the same numbers and easing;
 * - no stylesheet under src declares a duration of its own in a transition or an animation
 *   (an instant `0s` switch is not a duration);
 * - under the reduced-motion preference every token is zero and the global rule stops every
 *   transition and animation, and `motionDuration` answers zero.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import {
  MOTION_EASE,
  MOTION_MS,
  MOTION_RANGES,
  REDUCED_MOTION_QUERY,
  motionDuration,
  prefersReducedMotion,
} from "./motion";

const SRC = join(__dirname, "..");
const TOKENS = readFileSync(join(__dirname, "tokens.css"), "utf-8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);
const TOKEN_NAMES = {
  uiFast: "--motion-ui-fast",
  ui: "--motion-ui",
  data: "--motion-data",
} as const;

function rootBlock(css: string): string {
  return css.match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
}

function reducedBlock(css: string): string {
  const start = css.indexOf("@media (prefers-reduced-motion: reduce)");
  return start < 0 ? "" : css.slice(start);
}

function token(block: string, name: string): string | undefined {
  return block.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1]?.trim();
}

function stylesheets(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return stylesheets(path);
    return path.endsWith(".css") ? [path] : [];
  });
}

/** The time literals of every transition and animation declaration, other than 0s or 0ms. */
function literalDurations(css: string): string[] {
  const declarations = css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .matchAll(/(?:^|[;{\s])(transition[\w-]*|animation[\w-]*)\s*:([^;]+);/g);
  return [...declarations].flatMap(([, property, value]) =>
    [...value!.matchAll(/(?<![\w-])(\d*\.?\d+)(ms|s)\b/g)]
      .filter(([, amount]) => Number(amount) !== 0)
      .map(([literal]) => `${property}: ${literal}`),
  );
}

const media = (matches: boolean) => ({
  matchMedia: (query: string) =>
    ({ matches: query === REDUCED_MOTION_QUERY && matches }) as MediaQueryList,
});

describe("the motion tokens", () => {
  it("are declared once on :root, inside #1136's ranges, and motion.ts mirrors them", () => {
    const root = rootBlock(TOKENS);
    for (const kind of Object.keys(MOTION_MS) as (keyof typeof MOTION_MS)[]) {
      expect(token(root, TOKEN_NAMES[kind])).toBe(`${MOTION_MS[kind]}ms`);
      const [low, high] = MOTION_RANGES[kind];
      expect(MOTION_MS[kind]).toBeGreaterThanOrEqual(low);
      expect(MOTION_MS[kind]).toBeLessThanOrEqual(high);
    }
    expect(token(root, "--motion-ease")).toBe(`cubic-bezier(${MOTION_EASE.join(", ")})`);
  });

  it("are all zero under the reduced-motion preference, beside the global stop", () => {
    const reduced = reducedBlock(TOKENS);
    for (const name of Object.values(TOKEN_NAMES)) expect(token(reduced, name)).toBe("0ms");
    expect(reduced).toMatch(/animation:\s*none\s*!important/);
    expect(reduced).toMatch(/transition:\s*none\s*!important/);
  });
});

describe("the stylesheets", () => {
  it("declare no duration of their own: every transition and animation takes a token", () => {
    const offenders = stylesheets(SRC)
      .filter((path) => !path.endsWith(join("design", "tokens.css")))
      .flatMap((path) =>
        literalDurations(readFileSync(path, "utf-8")).map(
          (hit) => `${relative(SRC, path)}: ${hit}`,
        ),
      );
    expect(offenders).toEqual([]);
  });

  it("would catch a literal duration, so the check above can fail", () => {
    expect(literalDurations(".a { transition: transform 150ms ease; }")).toEqual([
      "transition: 150ms",
    ]);
    expect(literalDurations(".a { animation: in 0.3s; }")).toEqual(["animation: 0.3s"]);
    expect(literalDurations(".a { transition-duration: 2s; }")).toEqual([
      "transition-duration: 2s",
    ]);
    expect(literalDurations(".a { transition: visibility 0s linear var(--motion-ui); }")).toEqual(
      [],
    );
  });
});

describe("the reduced-motion switch in script", () => {
  it("reads the viewer's preference and answers zero under it", () => {
    expect(prefersReducedMotion(media(true))).toBe(true);
    expect(prefersReducedMotion(media(false))).toBe(false);
    expect(motionDuration("data", media(true))).toBe(0);
    expect(motionDuration("data", media(false))).toBe(MOTION_MS.data);
    expect(motionDuration("uiFast", media(false))).toBe(MOTION_MS.uiFast);
  });

  it("moves at full duration where the browser cannot say", () => {
    expect(prefersReducedMotion(undefined)).toBe(false);
    expect(prefersReducedMotion({} as Pick<Window, "matchMedia">)).toBe(false);
    expect(motionDuration("ui", undefined)).toBe(MOTION_MS.ui);
  });
});
