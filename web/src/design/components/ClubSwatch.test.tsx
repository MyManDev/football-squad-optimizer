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

  it.each([null, undefined, "", "XYZ"])("draws nothing for a club with no colours (%s)", (code) => {
    const { container } = render(<ClubSwatch code={code} split />);
    expect(container).toBeEmptyDOMElement();
  });
});
