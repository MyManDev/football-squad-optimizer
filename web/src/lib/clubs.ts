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

/** A club's two recognised home colours: the one its shirt is known by, then the other. */
export interface ClubColours {
  primary: string;
  secondary: string;
}

/**
 * Two colours per club code. The primary is the one-colour swatch beside a code on the
 * boards, plates and squad lists, and it keeps the value those pages have always drawn; a
 * fixture list draws both, split on the diagonal with the primary top left. Either is
 * decoration: the code or the name is always printed beside it, and the ink outline keeps
 * a white half visible on a light page.
 */
export const CLUB_COLOURS: Readonly<Record<string, ClubColours>> = {
  ARS: { primary: "#EF0107", secondary: "#FFFFFF" },
  AVL: { primary: "#670E36", secondary: "#95BFE5" },
  BHA: { primary: "#0057B8", secondary: "#FFFFFF" },
  BOU: { primary: "#B50E12", secondary: "#000000" },
  BRE: { primary: "#E30613", secondary: "#FFFFFF" },
  CHE: { primary: "#034694", secondary: "#FFFFFF" },
  COV: { primary: "#6CBFE8", secondary: "#FFFFFF" },
  CRY: { primary: "#1B458F", secondary: "#C4122E" },
  EVE: { primary: "#003399", secondary: "#FFFFFF" },
  FUL: { primary: "#000000", secondary: "#FFFFFF" },
  HUL: { primary: "#F5A12D", secondary: "#000000" },
  IPS: { primary: "#3A64A3", secondary: "#FFFFFF" },
  LEE: { primary: "#FFCD00", secondary: "#FFFFFF" },
  LIV: { primary: "#C8102E", secondary: "#FFFFFF" },
  MCI: { primary: "#6CABDD", secondary: "#FFFFFF" },
  MUN: { primary: "#DA291C", secondary: "#FFFFFF" },
  NEW: { primary: "#241F20", secondary: "#FFFFFF" },
  NFO: { primary: "#DD0000", secondary: "#FFFFFF" },
  SUN: { primary: "#EB172B", secondary: "#FFFFFF" },
  TOT: { primary: "#132257", secondary: "#FFFFFF" },
};

/** One swatch per club code: its primary colour, read from CLUB_COLOURS. */
export const CLUB_SWATCHES: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(CLUB_COLOURS).map(([code, colours]) => [code, colours.primary]),
);

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

/** Both colours for a club code, or `null` when the code has none. */
export function clubColours(code: string | null | undefined): ClubColours | null {
  if (!code) return null;
  return CLUB_COLOURS[code.toUpperCase()] ?? null;
}

/** The swatch colour for a club code (its primary), or `null` when the code has none. */
export function clubSwatch(code: string | null | undefined): string | null {
  return clubColours(code)?.primary ?? null;
}
