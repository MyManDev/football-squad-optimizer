/**
 * The colour tokens keep text readable (#1136): each text colour reaches 4.5:1 (WCAG AA for
 * body text) on every surface tokens.css lets it sit on, computed with the WCAG formula from
 * the token values, so changing a colour cannot quietly break a pairing the header promises.
 *
 * The pairs come from the header of tokens.css. Two of its stated limits are held as limits
 * here too: ink3 and the good green stay off the sidebar (--color-surface-2), and no small
 * text sits directly on the grass, so both stay below 4.5:1 there and the header stays true.
 * A new colour combination (a club colour, another pitch look) joins the table below.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const TOKENS = readFileSync(join(__dirname, "tokens.css"), "utf-8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);
const ROOT = TOKENS.match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";

function hex(name: string): string {
  const value = ROOT.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6});`))?.[1];
  if (value === undefined) throw new Error(`${name} is not a six-digit hex colour on :root`);
  return value;
}

function luminance(colour: string): number {
  const channels = [1, 3, 5].map((start) => parseInt(colour.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

export function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light! + 0.05) / (dark! + 0.05);
}

const AA = 4.5;

/** [text token, surface token]: every pairing the page uses for text. */
const READABLE: readonly (readonly [string, string])[] = [
  ["--color-text", "--color-bg"],
  ["--color-text", "--color-surface"],
  ["--color-text", "--color-surface-2"],
  ["--color-text-muted", "--color-bg"],
  ["--color-text-muted", "--color-surface"],
  ["--color-text-muted", "--color-surface-2"],
  ["--color-text-faint", "--color-bg"],
  ["--color-text-faint", "--color-surface"],
  ["--color-accent", "--color-bg"],
  ["--color-accent-text", "--color-accent"],
  ["--color-primary-text", "--color-primary"],
  ["--color-warn", "--color-surface-2"],
  ["--color-chip-text", "--color-chip"],
  ["--color-chip-muted", "--color-chip"],
  ["#ffffff", "--color-out-panel"],
  ["#ffffff", "--color-in-panel"],
  ["--color-lime", "--color-board"],
  ["--color-board-muted", "--color-board"],
  ["--color-text", "--color-seg2"],
  ["--color-text", "--color-lime"],
];

/** Pairings tokens.css says never carry text, held below AA so that sentence stays true. */
const KEPT_APART: readonly (readonly [string, string])[] = [
  ["--color-text-faint", "--color-surface-2"],
  ["--color-good", "--color-surface-2"],
  ["#ffffff", "--color-pitch"],
  ["--color-text", "--color-pitch"],
];

const colour = (token: string) => (token.startsWith("#") ? token : hex(token));

describe("the colour tokens", () => {
  it.each(READABLE)("%s on %s reaches 4.5:1", (foreground, background) => {
    expect(contrast(colour(foreground), colour(background))).toBeGreaterThanOrEqual(AA);
  });

  it.each(KEPT_APART)(
    "%s on %s stays below 4.5:1, as the header says",
    (foreground, background) => {
      expect(contrast(colour(foreground), colour(background))).toBeLessThan(AA);
    },
  );

  it("computes the WCAG ratio the header quotes", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast(hex("--color-text"), hex("--color-bg"))).toBeCloseTo(14.1, 1);
    expect(contrast(hex("--color-text-faint"), hex("--color-bg"))).toBeCloseTo(4.78, 2);
  });
});
