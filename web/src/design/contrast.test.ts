/**
 * The colour tokens keep text readable (#1136): each text colour reaches 4.5:1 (WCAG AA for
 * body text) on every surface tokens.css lets it sit on, computed with the WCAG formula from
 * the token values, so changing a colour cannot quietly break a pairing the header promises.
 *
 * The pairs come from the header of tokens.css, and they include the players of the page's
 * background scene, since page text passes over them. One of its stated limits is held as a
 * limit here too: no small text sits directly on the grass, so both inks stay below 4.5:1
 * there and the header stays true. The night palette is held to every day pairing, and its
 * two blocks (the system's preference, the viewer's choice) to the same values.
 *
 * Every stylesheet is read for the mark: a rule that paints it names --color-mark-text, and so
 * does every rule for what stands on that fill, since at night the page's own inks all but
 * vanish on it.
 *
 * The club pairings join it: every club's fill and text colour reach 4.5:1, as each
 * player's shirt is drawn in them. Of the two grass tokens, only the darker
 * (--color-pitch) is held below 4.5:1 for white and ink above; --color-pitch-2 is not held.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { clubPlate, PLATE_INK, PLATE_WHITE } from "../features/league/components/clubPlate";
import { CLUB_COLOURS } from "../lib/clubs";
import { AA, contrastRatio } from "./contrastRatio";

const TOKENS = readFileSync(join(__dirname, "tokens.css"), "utf-8").replace(
  /\/\*[\s\S]*?\*\//g,
  "",
);
const ROOT = TOKENS.match(/:root\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";
/** The night palette, as the system's dark preference sets it and as the viewer's choice. */
const NIGHT_BY_SYSTEM =
  TOKENS.match(/:root:not\(\[data-theme="light"\]\)\s*\{([\s\S]*?)\n {2}\}/)?.[1] ?? "";
const NIGHT_BY_CHOICE = TOKENS.match(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";

function tokenHex(block: string, name: string): string {
  const value = block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6});`))?.[1];
  if (value === undefined) throw new Error(`${name} is not a six-digit hex colour in the palette`);
  return value;
}

const hex = (name: string) => tokenHex(ROOT, name);

/** A palette's declarations, one per line and trimmed, so the two night blocks compare. */
const declarations = (block: string) =>
  block
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

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
  ["--color-text-faint", "--color-surface-2"],
  ["--color-accent", "--color-bg"],
  ["--color-primary-text", "--color-primary"],
  ["--color-warn", "--color-surface-2"],
  ["--color-good", "--color-bg"],
  ["--color-good", "--color-surface"],
  ["--color-good", "--color-surface-2"],
  ["--color-bad", "--color-bg"],
  ["--color-bad", "--color-surface"],
  ["--color-bad", "--color-surface-2"],
  ["--color-chip-text", "--color-chip"],
  ["--color-chip-muted", "--color-chip"],
  ["--color-board-text", "--color-out-panel"],
  ["--color-board-text", "--color-in-panel"],
  ["--color-board-text", "--color-board"],
  ["--color-mark", "--color-board"],
  ["--color-board-muted", "--color-board"],
  ["--color-mark-text", "--color-seg2"],
  ["--color-mark-text", "--color-mark"],
  // A goalkeeper's initials on the keepers' shirt.
  ["--color-mark-text", "--color-keeper"],
  // Page text over the background scene's players.
  ...["--color-scene", "--color-scene-far"].flatMap((player) =>
    [
      "--color-text",
      "--color-text-muted",
      "--color-text-faint",
      "--color-accent",
      "--color-good",
      "--color-bad",
      "--color-warn",
    ].map((text) => [text, player] as const),
  ),
];

/** At night links sit on panels too, in yellow. */
const NIGHT_READABLE: readonly (readonly [string, string])[] = [
  ...READABLE,
  ["--color-accent", "--color-surface"],
];

/** Pairings tokens.css says never carry text, held below AA so that sentence stays true. */
const KEPT_APART: readonly (readonly [string, string])[] = [
  ["#ffffff", "--color-pitch"],
  ["--color-text", "--color-pitch"],
];

/** At night the page's inks are as light as the mark, so only --color-mark-text reads on it. */
const NIGHT_KEPT_APART: readonly (readonly [string, string])[] = [
  ["--color-text", "--color-mark"],
  ["--color-text-muted", "--color-mark"],
  ["--color-text-faint", "--color-mark"],
  ["--color-focus", "--color-mark"],
];

const colour = (token: string, block = ROOT) =>
  token.startsWith("#") ? token : tokenHex(block, token);

const SRC = join(__dirname, "..");

function stylesheets(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return stylesheets(path);
    return path.endsWith(".css") ? [path] : [];
  });
}

/** A stylesheet's rules, one per selector of a list, the ones inside an at-rule among them. */
function rulesOf(css: string) {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)].flatMap(([, selectors, body]) =>
    selectors!.split(",").map((selector) => ({ selector: selector.trim(), body: body! })),
  );
}

const PAINTS_THE_MARK = /(?:^|[;\s])background(?:-color)?:\s*var\(--color-mark\);/;
const PAINTS_ANOTHER_FILL = /(?:^|[;\s])background(?:-color)?:/;
const INK_ON_THE_MARK = /(?:^|[;\s])color:\s*var\(--color-mark-text\);/;

/**
 * Whether a selector reaches what stands on a fill. `.viewerRow td` fills the row's cells, so
 * what is in them is named from the row: `.viewerRow .manager`.
 */
function standsOn(selector: string, fill: string): boolean {
  const holder = fill.replace(/ [a-z]+$/, "");
  return (
    selector !== fill &&
    selector.startsWith(holder) &&
    /^[\s.:[]/.test(selector.slice(holder.length))
  );
}

/** What a rule draws in other than the mark's own ink: its text, its borders, its marks. */
function otherInks(body: string): string[] {
  return [...body.matchAll(/(?:^|[;\s])((?:color|fill|stroke|border[a-z-]*):\s*[^;]+);/g)]
    .map(([, declaration]) => declaration!)
    .filter((declaration) => /var\(--color-(?!mark-text\))/.test(declaration));
}

/** Every rule that paints the mark, and what the rules for the things standing on it draw with. */
const MARK_FILLS = stylesheets(SRC).flatMap((path) => {
  const rules = rulesOf(readFileSync(path, "utf-8"));
  const sheet = relative(SRC, path).replaceAll("\\", "/");
  return rules
    .filter(({ body }) => PAINTS_THE_MARK.test(body))
    .map(({ selector, body }) => ({
      fill: `${sheet} ${selector}`,
      ink: body,
      onIt: rules
        .filter((rule) => standsOn(rule.selector, selector) && !PAINTS_ANOTHER_FILL.test(rule.body))
        .flatMap((rule) => otherInks(rule.body).map((ink) => `${rule.selector} ${ink}`)),
    }));
});

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
    expect(contrast(hex("--color-text"), hex("--color-bg"))).toBeCloseTo(16, 0);
    expect(contrast(hex("--color-text-faint"), hex("--color-bg"))).toBeCloseTo(6, 0);
  });
});

describe("the night palette", () => {
  const night = (name: string) => tokenHex(NIGHT_BY_CHOICE, name);
  const names = (block: string) =>
    [...block.matchAll(/(--color-[a-z0-9-]+):/g)].map((match) => match[1]).sort();

  it("is the same whether the system asks for it or the viewer chose it", () => {
    expect(declarations(NIGHT_BY_SYSTEM)).toEqual(declarations(NIGHT_BY_CHOICE));
    expect(declarations(NIGHT_BY_CHOICE)).toContain("color-scheme: dark;");
  });

  it("sets every colour the day sets", () => {
    expect(names(NIGHT_BY_CHOICE)).toEqual(names(ROOT));
  });

  it.each(NIGHT_READABLE)("%s on %s reaches 4.5:1", (foreground, background) => {
    const ratio = contrast(
      colour(foreground, NIGHT_BY_CHOICE),
      colour(background, NIGHT_BY_CHOICE),
    );
    expect(ratio).toBeGreaterThanOrEqual(AA);
  });

  it.each(NIGHT_KEPT_APART)(
    "%s on %s stays below 4.5:1, so nothing but the mark's ink stands on it",
    (foreground, background) => {
      const ratio = contrast(
        colour(foreground, NIGHT_BY_CHOICE),
        colour(background, NIGHT_BY_CHOICE),
      );
      expect(ratio).toBeLessThan(AA);
    },
  );

  it("computes the ratios the header quotes", () => {
    expect(contrast(night("--color-text"), night("--color-bg"))).toBeCloseTo(15.7, 1);
    expect(contrast(night("--color-text-faint"), night("--color-surface"))).toBeCloseTo(5.7, 1);
    expect(contrast(night("--color-mark-text"), night("--color-mark"))).toBeCloseTo(11.3, 1);
    expect(contrast(night("--color-text"), night("--color-mark"))).toBeCloseTo(1.4, 1);
  });
});

describe("the mark's fill", () => {
  it("is read wherever the viewer's own rows, a focused name and a changed row draw it", () => {
    expect(MARK_FILLS.map(({ fill }) => fill)).toEqual(
      expect.arrayContaining([
        "features/league/pages/LeagueMembersPage.module.css .viewerRow td",
        "features/league/race/LeagueRaceCard.module.css .gaps li[aria-current]",
        "features/league/pages/MemberPicker.module.css .option:focus-visible",
        "features/league/device/WhatIfPanel.module.css .player[data-changed]",
      ]),
    );
  });

  it.each(MARK_FILLS.map((mark) => [mark.fill, mark] as const))(
    "%s has its own ink, on it and on what stands on it",
    (_fill, mark) => {
      expect(mark.ink).toMatch(INK_ON_THE_MARK);
      expect(mark.onIt).toEqual([]);
    },
  );
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
