/**
 * The colour tokens keep text readable (#1136): each text colour reaches 4.5:1 (WCAG AA for
 * body text) on every surface tokens.css lets it sit on, computed with the WCAG formula from
 * the token values, so changing a colour cannot quietly break a pairing the header promises.
 *
 * The pairs come from the header of tokens.css. Two of its stated limits are held as limits
 * here too: ink3 and the good green stay off the sidebar (--color-surface-2), and no small
 * text sits directly on the grass, so both stay below 4.5:1 there and the header stays true.
 *
 * The viewer's pitch looks join it: every club plate's fill and text colour reach 4.5:1
 * (the header's one exception to the white plates), and every grass look is drawn in the
 * two grass tokens only. Of those two, only the darker (--color-pitch) is held below 4.5:1
 * for white and ink above; --color-pitch-2 is not held.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { clubPlate, PLATE_INK, PLATE_WHITE } from "../features/league/components/pitchLook";
import { CLUB_COLOURS } from "../lib/clubs";
import { AA, contrastRatio } from "./contrastRatio";

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

const contrast = contrastRatio;

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
  ["--color-good", "--color-bg"],
  ["--color-good", "--color-surface"],
  ["--color-bad", "--color-bg"],
  ["--color-bad", "--color-surface"],
  ["--color-bad", "--color-surface-2"],
  ["--color-chip-text", "--color-chip"],
  ["--color-chip-muted", "--color-chip"],
  ["#ffffff", "--color-out-panel"],
  ["#ffffff", "--color-in-panel"],
  ["--color-lime", "--color-board"],
  ["--color-board-muted", "--color-board"],
  ["--color-text", "--color-seg2"],
  ["--color-text", "--color-lime"],
  // A goalkeeper's initials on the keepers' shirt.
  ["--color-text", "--color-keeper"],
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

describe("the club plates", () => {
  it("print in the page's ink or in white", () => {
    expect(PLATE_INK).toBe(hex("--color-text"));
    expect(PLATE_WHITE).toBe(hex("--color-chip"));
  });

  it.each(Object.keys(CLUB_COLOURS))("%s's plate text reaches 4.5:1 on its fill", (code) => {
    const plate = clubPlate(code)!;
    expect(plate).not.toBeNull();
    expect(plate.fill).toBe(CLUB_COLOURS[code]![plate.colour]);
    expect(contrast(plate.text, plate.fill)).toBeGreaterThanOrEqual(AA);
  });

  it("take the primary where it reads, and the secondary only where it does not", () => {
    expect(clubPlate("TOT")).toEqual({ colour: "primary", fill: "#132257", text: PLATE_WHITE });
    expect(clubPlate("LEE")).toEqual({ colour: "primary", fill: "#FFCD00", text: PLATE_INK });
    // Arsenal's red reads 4.49:1 with white and 3.56:1 with ink: its white second colour.
    expect(clubPlate("ARS")).toEqual({ colour: "secondary", fill: "#FFFFFF", text: PLATE_INK });
    expect(clubPlate("XYZ")).toBeNull();
    expect(clubPlate(null)).toBeNull();
  });
});

describe("the grass looks", () => {
  const css = readFileSync(
    join(__dirname, "../features/league/components/MemberPitch.module.css"),
    "utf-8",
  ).replace(/\/\*[\s\S]*?\*\//g, "");

  it.each(["plain", "checks"])("%s is drawn in the grass tokens only", (look) => {
    const rules = [
      ...css.matchAll(new RegExp(`\\[data-grass="${look}"\\] \\.field \\{([^}]*)\\}`, "g")),
    ];
    expect(rules.length).toBeGreaterThan(0);
    for (const [, body] of rules) {
      expect(body).not.toMatch(/#[0-9a-f]{3,8}\b|rgb|hsl/i);
      for (const token of body!.match(/--color-[a-z0-9-]+/g) ?? [])
        expect(["--color-pitch", "--color-pitch-2"]).toContain(token);
    }
  });
});
