import { readFileSync } from "node:fs";
import { join } from "node:path";

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CLUB_COLOURS } from "../../lib/clubs";
import { ClubSwatch } from "./ClubSwatch";

/** The twenty clubs of the 2026-27 season, by the code the fixture list prints. */
const SEASON_CODES = [
  "ARS",
  "AVL",
  "BHA",
  "BOU",
  "BRE",
  "CHE",
  "COV",
  "CRY",
  "EVE",
  "FUL",
  "HUL",
  "IPS",
  "LEE",
  "LIV",
  "MCI",
  "MUN",
  "NEW",
  "NFO",
  "SUN",
  "TOT",
] as const;

/** The swatch's stylesheet without its comments. */
const stylesheet = () =>
  readFileSync(join(__dirname, "ClubSwatch.module.css"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");

/** The declarations of one rule, whitespace folded, or `undefined` when the rule is missing. */
const rule = (selector: string) =>
  stylesheet()
    .match(new RegExp(String.raw`(^|\n)\.${selector}\s*\{([^}]*)\}`))?.[2]
    ?.replace(/\s+/g, " ")
    .trim();

afterEach(cleanup);

describe("the club swatch", () => {
  it.each(SEASON_CODES)("draws both of %s's colours, split, as decoration", (code) => {
    const { container } = render(<ClubSwatch code={code} split />);
    const swatch = container.firstElementChild as HTMLElement;
    expect(swatch).toHaveAttribute("aria-hidden", "true");
    expect(swatch).toHaveClass("swatch", "split");
    expect(swatch.textContent).toBe("");
    expect(swatch.style.getPropertyValue("--club-primary")).toBe(CLUB_COLOURS[code]!.primary);
    expect(swatch.style.getPropertyValue("--club-secondary")).toBe(CLUB_COLOURS[code]!.secondary);
  });

  it("draws the primary colour alone unless asked for both", () => {
    const { container } = render(<ClubSwatch code="avl" />);
    const swatch = container.firstElementChild as HTMLElement;
    expect(swatch).toHaveAttribute("aria-hidden", "true");
    expect(swatch).not.toHaveClass("split");
    expect(swatch.style.background).toMatch(/#670E36|rgb\(103, 14, 54\)/i);
    expect(swatch.style.getPropertyValue("--club-secondary")).toBe("");
  });

  it.each([
    ["TOT", "rgb(19, 34, 87)"],
    ["FUL", "rgb(0, 0, 0)"],
    ["LEE", "rgb(255, 205, 0)"],
  ])("draws %s's one-colour swatch in the colour the boards always had", (code, colour) => {
    const { container } = render(<ClubSwatch code={code} />);
    expect((container.firstElementChild as HTMLElement).style.backgroundColor).toBe(colour);
  });

  it("paints the split as the two colours, half and half on the diagonal", () => {
    // The custom properties above carry the colours; this rule is what paints them. Without
    // it every fixture mark would be an empty outlined square.
    const split = rule("split");
    expect(split).toBeDefined();
    expect(split).toMatch(
      /background(-image)?: linear-gradient\(\s*135deg,\s*var\(--club-primary\) 50%,\s*var\(--club-secondary\) 50%\s*\);/,
    );
    // The square and its ink outline, which keeps a white half visible.
    const swatch = rule("swatch");
    expect(swatch).toContain("width: 10px;");
    expect(swatch).toContain("height: 10px;");
    expect(swatch).toContain("outline: 1px solid var(--color-board);");
    // No other rule in the sheet sets a background that could paint over the split.
    expect(stylesheet().match(/background/g)).toHaveLength(1);
  });

  it.each([null, undefined, "", "XYZ"])("draws nothing for a club with no colours (%s)", (code) => {
    const { container } = render(<ClubSwatch code={code} split />);
    expect(container).toBeEmptyDOMElement();
  });
});
