import { clubCode, type ClubCodes } from "../../../lib/clubs";
import type { FixturesPayload } from "../../fixtures/types";

/** The documents a week is read from: the season and capture the calendar must match. */
interface WeekBasis {
  season: string;
  source_snapshot_id: string | null;
  gameweek: number;
}

/**
 * Each club's opponent in the basis week, as a plate prints it: the opponent's code and
 * where the club plays, `BOU (E)` at home and `BOU (D)` away (`(H)` and `(A)` in English).
 * A club with two matches that week prints the first and `+1`; a club with none prints a
 * hyphen. Null for every club where the calendar is not the basis's own capture, so a plate
 * never prints another capture's week.
 */
export function weekOpponents(
  fixtures: FixturesPayload | null | undefined,
  basis: WeekBasis | null | undefined,
  codes: ClubCodes,
  language: "tr" | "en",
): (team: string) => string | null {
  const calendar =
    basis &&
    fixtures?.season === basis.season &&
    fixtures.source_snapshot_id === basis.source_snapshot_id
      ? fixtures
      : null;
  const week = calendar?.gameweeks.find((row) => row.gameweek === basis?.gameweek);
  if (!week) return () => null;
  const home = language === "tr" ? "E" : "H";
  const away = language === "tr" ? "D" : "A";
  return (team) => {
    const code = clubCode(team, codes);
    const same = (side: { name: string; short_name: string }) =>
      side.name.trim().toLocaleLowerCase("en-GB") === team.trim().toLocaleLowerCase("en-GB") ||
      (code !== null && side.short_name === code);
    const matches = week.fixtures.filter((match) => same(match.home) || same(match.away));
    const first = matches[0];
    if (!first) return "-";
    const atHome = same(first.home);
    const opponent = atHome ? first.away : first.home;
    const text = `${opponent.short_name} (${atHome ? home : away})`;
    return matches.length > 1 ? `${text} +${matches.length - 1}` : text;
  };
}

/** A price in tenths as the game prints it: `£7,1` in Turkish, `£7.1` in English. */
export function priceText(tenths: number, locale: string): string {
  return `£${(tenths / 10).toLocaleString(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}`;
}
