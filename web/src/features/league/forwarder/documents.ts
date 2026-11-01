/**
 * The FPL forwarder's three documents (ADR 0012), read by hand as the repository's other
 * readers are: every field its contract names, with its type and range, and the identities
 * the request asked for. A document that is not exactly that reads as null, never as part
 * of one. The contracts are `docs/contracts/fpl_league_standings_v1.md`,
 * `fpl_entry_bundle_v1.md` and `week_live_v1.md`.
 */

import {
  memberWeek,
  weekLive,
  WeekLiveError,
  type MemberWeek,
  type WeekLive,
} from "../../liveScore/weekLive";

export const STANDINGS_CONTRACT = "fpl_league_standings_v1";
export const BUNDLE_CONTRACT = "fpl_entry_bundle_v1";
export const LIVE_CONTRACT = "week_live_v1";

/** The forwarder reads classic leagues of up to 20 pages. */
export const MAX_STANDINGS_PAGE = 20;
export const LAST_GAMEWEEK = 38;

export interface FplStandingRow {
  entry: number;
  entry_name: string;
  player_name: string;
  rank: number;
  rank_sort: number;
  last_rank: number | null;
  total: number;
  event_total: number;
}

export interface FplLeagueStandings {
  contract_version: typeof STANDINGS_CONTRACT;
  league: { id: number; name: string | null; scoring: "classic" };
  page: number;
  has_next: boolean;
  last_updated_data: string | null;
  source_time: string;
  results: FplStandingRow[];
}

export interface FplHistoryWeek {
  event: number;
  event_transfers: number;
  event_transfers_cost: number;
  bank: number | null;
}

export interface FplTransfer {
  entry: number;
  event: number;
  time: string;
  element_in: number;
  element_in_cost: number;
  element_out: number;
  element_out_cost: number;
}

export interface FplWeekPicks {
  active_chip: string | null;
  automatic_subs: { entry: number; event: number; element_in: number; element_out: number }[];
  entry_history: { event: number; bank: number; value: number };
  picks: {
    element: number;
    position: number;
    multiplier: number;
    is_captain: boolean;
    is_vice_captain: boolean;
  }[];
}

export interface FplEntryBundle {
  contract_version: typeof BUNDLE_CONTRACT;
  entry_id: number;
  /** The table gameweek the bundle was asked for. */
  gameweek: number;
  source_time: string;
  entry: { id: number; name: string; started_event: number };
  history: { current: FplHistoryWeek[]; chips: { name: string; event: number }[] };
  transfers: FplTransfer[];
  /** One picks document per week read, in week order. */
  picks: FplWeekPicks[];
  /** The member's week of the latest passed deadline, in `week_live_v1`'s member shape. */
  current_week: MemberWeek | null;
}

class Unreadable extends Error {}

function need(ok: boolean): void {
  if (!ok) throw new Unreadable();
}

function record(value: unknown): Record<string, unknown> {
  need(typeof value === "object" && value !== null && !Array.isArray(value));
  return value as Record<string, unknown>;
}

function list(value: unknown): unknown[] {
  need(Array.isArray(value));
  return value as unknown[];
}

const integer = (value: unknown): value is number => Number.isSafeInteger(value);
const count = (value: unknown): value is number => integer(value) && value >= 0;
const id = (value: unknown): value is number => integer(value) && value >= 1;
const week = (value: unknown): value is number => id(value) && value <= LAST_GAMEWEEK;
const text = (value: unknown): value is string => typeof value === "string";
const flag = (value: unknown): value is boolean => typeof value === "boolean";

const SOURCE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

/** A UTC time as the contracts write it, and a real calendar instant (no 31 February). */
function sourceTime(value: unknown): boolean {
  if (!text(value) || !SOURCE_TIME.test(value)) return false;
  const parsed = new Date(value);
  return (
    Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 19) === value.slice(0, 19)
  );
}

function readOrNull<T>(read: () => T): T | null {
  try {
    return read();
  } catch (error) {
    if (error instanceof Unreadable || error instanceof WeekLiveError) return null;
    throw error;
  }
}

/** One page of a classic league, when it is the page of the league asked for. */
export function readStandings(
  value: unknown,
  league: number,
  page: number,
): FplLeagueStandings | null {
  return readOrNull(() => {
    const document = record(value);
    need(document.contract_version === STANDINGS_CONTRACT);
    const named = record(document.league);
    need(named.id === league && (named.name === null || text(named.name)));
    need(named.scoring === "classic");
    need(document.page === page && page >= 1 && page <= MAX_STANDINGS_PAGE);
    need(flag(document.has_next));
    need(document.last_updated_data === null || text(document.last_updated_data));
    need(sourceTime(document.source_time));
    const entries = list(document.results).map((value) => {
      const row = record(value);
      need(
        id(row.entry) &&
          text(row.entry_name) &&
          text(row.player_name) &&
          count(row.rank) &&
          id(row.rank_sort) &&
          (row.last_rank === null || count(row.last_rank)) &&
          integer(row.total) &&
          integer(row.event_total),
      );
      return row.entry;
    });
    need(new Set(entries).size === entries.length);
    return document as unknown as FplLeagueStandings;
  });
}

function readWeekPicks(value: unknown): number {
  const document = record(value);
  need(document.active_chip === null || text(document.active_chip));
  for (const value of list(document.automatic_subs)) {
    const row = record(value);
    need(id(row.entry) && week(row.event) && id(row.element_in) && id(row.element_out));
  }
  const history = record(document.entry_history);
  need(week(history.event) && count(history.bank) && count(history.value));
  for (const value of list(document.picks)) {
    const row = record(value);
    need(
      id(row.element) &&
        id(row.position) &&
        count(row.multiplier) &&
        flag(row.is_captain) &&
        flag(row.is_vice_captain),
    );
  }
  return history.event as number;
}

/**
 * One entry's bundle, when it is the bundle of the entry and the table gameweek asked for:
 * every transfer is that entry's, the picks are in week order from its joining week up to
 * the held week (the table gameweek minus 1), and its current week is that entry's and no
 * earlier than the held week.
 */
export function readEntryBundle(
  value: unknown,
  entry: number,
  gameweek: number,
): FplEntryBundle | null {
  return readOrNull(() => {
    const document = record(value);
    need(document.contract_version === BUNDLE_CONTRACT);
    need(document.entry_id === entry && document.gameweek === gameweek);
    need(gameweek >= 2 && gameweek <= LAST_GAMEWEEK);
    need(sourceTime(document.source_time));
    const own = record(document.entry);
    need(own.id === entry && text(own.name) && week(own.started_event));
    const history = record(document.history);
    for (const value of list(history.current)) {
      const row = record(value);
      need(
        week(row.event) &&
          count(row.event_transfers) &&
          count(row.event_transfers_cost) &&
          (row.bank === null || integer(row.bank)),
      );
    }
    for (const value of list(history.chips)) {
      const row = record(value);
      need(text(row.name) && week(row.event));
    }
    for (const value of list(document.transfers)) {
      const row = record(value);
      need(
        row.entry === entry &&
          week(row.event) &&
          text(row.time) &&
          id(row.element_in) &&
          count(row.element_in_cost) &&
          id(row.element_out) &&
          count(row.element_out_cost),
      );
    }
    const weeks = list(document.picks).map(readWeekPicks);
    need(weeks.every((at, index) => index === 0 || at > weeks[index - 1]!));
    need(weeks.every((at) => at >= (own.started_event as number) && at < gameweek));
    const current = document.current_week;
    if (current !== null) {
      const row = record(current);
      need(week(row.gameweek));
      const read = memberWeek(row, row.gameweek as number);
      need(read.entry_id === entry && read.gameweek >= gameweek - 1);
    }
    return document as unknown as FplEntryBundle;
  });
}

/**
 * One week's live points, when it is the week asked for and in the forwarder's form: without
 * member blocks and without positions or clubs, which the page resolves from the capture's
 * table (`week_live_v1.md`, source A).
 */
export function readLiveWeek(value: unknown, gameweek: number): WeekLive | null {
  return readOrNull(() => {
    const document = weekLive(value);
    need(document.gameweek === gameweek && document.members === undefined);
    need(document.elements.every((row) => row.position === undefined && row.club === undefined));
    return document;
  });
}
