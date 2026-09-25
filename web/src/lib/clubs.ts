/**
 * Club codes and swatches.
 *
 * A published player record names its club the way the game displays it ('Man Utd',
 * 'Ipswich Town'); the three-letter code the boards, plates and fixture cells print lives
 * only in fixtures.json, where each side of every fixture carries its club's name and
 * short name. So the code is read from the fixture list first. The static map below covers
 * the season's twenty clubs for when that document is absent, and a club neither knows
 * has no code: it is shown by name, never under an invented abbreviation.
 */

/** Just the part of fixtures_v1 this module reads. */
export interface ClubFixtureList {
  gameweeks: ReadonlyArray<{
    fixtures: ReadonlyArray<{
      home: { name: string; short_name: string };
      away: { name: string; short_name: string };
    }>;
  }>;
}

/** Club codes read from a fixture list, keyed by a normalised name: read it with clubCode(). */
export type ClubCodes = ReadonlyMap<string, string>;

/**
 * The 2026-27 clubs under the names fixtures.json and the league documents publish, plus
 * the long names a document might use instead.
 */
const FALLBACK_CODES: Readonly<Record<string, string>> = {
  Arsenal: "ARS",
  "Aston Villa": "AVL",
  Bournemouth: "BOU",
  "AFC Bournemouth": "BOU",
  Brentford: "BRE",
  Brighton: "BHA",
  "Brighton & Hove Albion": "BHA",
  Chelsea: "CHE",
  "Coventry City": "COV",
  Coventry: "COV",
  "Crystal Palace": "CRY",
  Everton: "EVE",
  Fulham: "FUL",
  "Hull City": "HUL",
  Hull: "HUL",
  "Ipswich Town": "IPS",
  Ipswich: "IPS",
  Leeds: "LEE",
  "Leeds United": "LEE",
  Liverpool: "LIV",
  "Man City": "MCI",
  "Manchester City": "MCI",
  "Man Utd": "MUN",
  "Manchester United": "MUN",
  Newcastle: "NEW",
  "Newcastle United": "NEW",
  "Nott'm Forest": "NFO",
  "Nottingham Forest": "NFO",
  Spurs: "TOT",
  Tottenham: "TOT",
  "Tottenham Hotspur": "TOT",
  Sunderland: "SUN",
};

/**
 * One swatch per club code (a 10 px square with an ink outline next to the code). The
 * colour is decoration: the code is always printed beside it.
 */
export const CLUB_SWATCHES: Readonly<Record<string, string>> = {
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

const key = (name: string) => name.trim().toLocaleLowerCase("en-GB");

const FALLBACK = new Map(Object.entries(FALLBACK_CODES).map(([name, code]) => [key(name), code]));

/** Every club name a fixture list names, with the short name printed beside it. */
export function clubCodesFromFixtures(fixtures: ClubFixtureList | null | undefined): ClubCodes {
  const codes = new Map<string, string>();
  for (const week of fixtures?.gameweeks ?? []) {
    for (const fixture of week.fixtures) {
      for (const side of [fixture.home, fixture.away]) {
        const code = side.short_name.trim();
        if (side.name.trim() !== "" && code !== "") codes.set(key(side.name), code);
      }
    }
  }
  return codes;
}

/**
 * The code for a club name: the fixture list's own short name when it names the club,
 * else the season's static map, else `null` (the club is shown by name).
 */
export function clubCode(team: string, fromFixtures?: ClubCodes | null): string | null {
  const name = key(team);
  if (name === "") return null;
  return fromFixtures?.get(name) ?? FALLBACK.get(name) ?? null;
}

/** The swatch colour for a club code, or `null` when the code has none. */
export function clubSwatch(code: string | null | undefined): string | null {
  if (!code) return null;
  return CLUB_SWATCHES[code.toUpperCase()] ?? null;
}
