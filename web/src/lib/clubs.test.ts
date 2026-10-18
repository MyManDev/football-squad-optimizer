import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  CLUB_COLOURS,
  CLUB_SWATCHES,
  clubCode,
  clubCodesFromFixtures,
  clubColours,
  clubSwatch,
} from "./clubs";
import type { ClubFixtureList } from "./clubs";

const published = JSON.parse(
  readFileSync(join(__dirname, "../../public/data/fixtures.json"), "utf-8"),
) as { payload: ClubFixtureList };

const fixture = (home: [string, string], away: [string, string]) => ({
  home: { name: home[0], short_name: home[1] },
  away: { name: away[0], short_name: away[1] },
});

describe("club codes", () => {
  it("reads the code from the fixture list's own short name", () => {
    const codes = clubCodesFromFixtures({
      gameweeks: [{ fixtures: [fixture(["Man Utd", "MUN"], ["Spurs", "TOT"])] }],
    });
    expect(clubCode("Man Utd", codes)).toBe("MUN");
    expect(clubCode("Spurs", codes)).toBe("TOT");
  });

  it("prefers what the fixture list publishes over the static map", () => {
    // A renamed short name in the published calendar wins over the built-in guess.
    const codes = clubCodesFromFixtures({
      gameweeks: [{ fixtures: [fixture(["Chelsea", "CFC"], ["Arsenal", "ARS"])] }],
    });
    expect(clubCode("Chelsea", codes)).toBe("CFC");
    expect(clubCode("Chelsea")).toBe("CHE");
  });

  it("falls back to the season's clubs when there is no fixture list", () => {
    expect(clubCode("Ipswich Town")).toBe("IPS");
    expect(clubCode("Ipswich Town", null)).toBe("IPS");
    expect(clubCode("Nott'm Forest", clubCodesFromFixtures(null))).toBe("NFO");
    expect(clubCode("Coventry City")).toBe("COV");
    expect(clubCode("Hull City")).toBe("HUL");
    expect(clubCode("Newcastle")).toBe("NEW");
    // Surrounding spaces and letter case do not hide a club.
    expect(clubCode("  man city ")).toBe("MCI");
  });

  it("gives an unknown club no code rather than an invented one", () => {
    // The example league's fictional clubs are shown by name.
    expect(clubCode("Northport")).toBeNull();
    expect(clubCode("")).toBeNull();
    expect(clubSwatch(null)).toBeNull();
    expect(clubSwatch("XYZ")).toBeNull();
  });

  it("covers every club the published calendar names, with a swatch for each", () => {
    const pairs = new Map<string, string>();
    for (const week of published.payload.gameweeks)
      for (const match of week.fixtures)
        for (const side of [match.home, match.away]) pairs.set(side.name, side.short_name);

    expect(pairs.size).toBe(20);
    for (const [name, code] of pairs) {
      // The static map agrees with the calendar, so a missing document changes nothing.
      expect(clubCode(name), name).toBe(code);
      expect(clubSwatch(code), code).toMatch(/^#[0-9A-F]{6}$/);
    }
    expect(Object.keys(CLUB_SWATCHES).sort()).toEqual([...pairs.values()].sort());
  });

  it("gives every club the calendar names two distinct colours, the primary its swatch", () => {
    const codes = new Set<string>();
    for (const week of published.payload.gameweeks)
      for (const match of week.fixtures)
        for (const side of [match.home, match.away]) codes.add(side.short_name);

    expect(Object.keys(CLUB_COLOURS).sort()).toEqual([...codes].sort());
    for (const code of codes) {
      const colours = clubColours(code)!;
      expect(colours.primary, code).toMatch(/^#[0-9A-F]{6}$/);
      expect(colours.secondary, code).toMatch(/^#[0-9A-F]{6}$/);
      expect(colours.secondary, code).not.toBe(colours.primary);
      expect(clubSwatch(code), code).toBe(colours.primary);
      expect(CLUB_SWATCHES[code], code).toBe(colours.primary);
    }
    expect(clubColours("ars")).toEqual({ primary: "#EF0107", secondary: "#FFFFFF" });
    expect(clubColours(null)).toBeNull();
    expect(clubColours("XYZ")).toBeNull();
  });

  it("pairs each club with its recognised home colours", () => {
    expect(clubColours("AVL")).toEqual({ primary: "#670E36", secondary: "#95BFE5" });
    expect(clubColours("NEW")).toEqual({ primary: "#241F20", secondary: "#FFFFFF" });
    expect(clubColours("MCI")).toEqual({ primary: "#6CABDD", secondary: "#FFFFFF" });
    expect(clubColours("HUL")).toEqual({ primary: "#F5A12D", secondary: "#000000" });
    expect(clubColours("CRY")).toEqual({ primary: "#1B458F", secondary: "#C4122E" });
    // The clubs that play in white keep their swatch colour first and take white second.
    expect(clubColours("TOT")).toEqual({ primary: "#132257", secondary: "#FFFFFF" });
    expect(clubColours("FUL")).toEqual({ primary: "#000000", secondary: "#FFFFFF" });
    expect(clubColours("LEE")).toEqual({ primary: "#FFCD00", secondary: "#FFFFFF" });
  });

  it("keeps the direction D swatches for every club, so the boards look as they did", () => {
    // The one-colour swatch the boards, plates, bench and squad lists draw. A change to the
    // two-colour pairs must never move one of these.
    const DIRECTION_D: Readonly<Record<string, string>> = {
      ARS: "#EF0107",
      AVL: "#670E36",
      BHA: "#0057B8",
      BOU: "#B50E12",
      BRE: "#E30613",
      CHE: "#034694",
      COV: "#6CBFE8",
      CRY: "#1B458F",
      EVE: "#003399",
      FUL: "#000000",
      HUL: "#F5A12D",
      IPS: "#3A64A3",
      LEE: "#FFCD00",
      LIV: "#C8102E",
      MCI: "#6CABDD",
      MUN: "#DA291C",
      NEW: "#241F20",
      NFO: "#DD0000",
      SUN: "#EB172B",
      TOT: "#132257",
    };
    expect(CLUB_SWATCHES).toEqual(DIRECTION_D);
    for (const [code, colour] of Object.entries(DIRECTION_D)) {
      expect(clubSwatch(code), code).toBe(colour);
      expect(clubSwatch(code.toLowerCase()), code).toBe(colour);
    }
    // None is plain white, which would vanish on a white pitch plate.
    expect(Object.values(CLUB_SWATCHES)).not.toContain("#FFFFFF");
  });
});
