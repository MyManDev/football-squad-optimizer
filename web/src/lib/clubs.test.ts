import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { CLUB_SWATCHES, clubCode, clubCodesFromFixtures, clubSwatch } from "./clubs";
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

  it("keeps the direction D swatches", () => {
    expect(clubSwatch("CHE")).toBe("#034694");
    expect(clubSwatch("mun")).toBe("#DA291C");
    expect(clubSwatch("COV")).toBe("#6CBFE8");
    expect(clubSwatch("HUL")).toBe("#F5A12D");
    expect(clubSwatch("NEW")).toBe("#241F20");
  });
});
