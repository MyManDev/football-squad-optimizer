/**
 * The LIVE page's board for one member: the live week's fifteen from one live read, each
 * pick in the group its match puts it in, with what the official scorer counts and the
 * state FPL's own points give it (the synthesis of 2026-11-11, sections 3.2 and 3.3).
 *
 * - A match's phase is read at the read's own source time, so the groups change only when a
 *   read does: a match is played from its kickoff (or from FPL's in-play list, where the read
 *   has event detail) until FPL calls it finished or `MATCH_WINDOW_MS` after its kickoff.
 * - The named eleven stand in Oynuyor, Oynayacak and Bitti by their match; picks 12 to 15
 *   stand in Yedekler in bench order. A double-week club takes its current fixture.
 * - A pick's state is FPL's points less what an appearance alone gives
 *   (`appearancePoints`), summed over his fixtures: one or more is İyi ilerliyor, minus one
 *   or less Zorlanıyor, and none is neutral. Bonus enters it only once FPL has added it. A
 *   double week needs each fixture's minutes, from the read's detail; without it no state is
 *   drawn. A pick who has not played and has no card and no points has no state.
 * - Oynamadı waits for FPL's finished; Maç yok is a club with no fixture this week.
 */

import type { Fixture, FixturesPayload } from "../../fixtures/types";
import { MATCH_WINDOW_MS } from "../../liveScore/liveWindow";
import type { LiveActivity } from "../../liveScore/weekActivity";
import type { MemberWeek, Position, WeekLive } from "../../liveScore/weekLive";
import { forecastSource } from "../device/chipForecast/member";
import type { DevicePlanDocument } from "../device/types";
import { memberLiveScore } from "./memberLiveScore";

/** Where a match stands at the read's source time. */
export type LivePhase = "upcoming" | "playing" | "finished";
/** The page's groups: the eleven by their match, then the bench. */
export type LiveGroup = LivePhase | "bench";
export type LiveState = "up" | "down" | "neutral";
/** A fact about the pick that is neither up nor down. */
export type LiveFact = "didNotPlay" | "noMatch";
/** What the member's score takes of a pick's points: none, once, the armband's two or three. */
export type Multiplier = 0 | 1 | 2 | 3;

export const LIVE_GROUPS: readonly LiveGroup[] = ["playing", "upcoming", "finished", "bench"];

/** One of a pick's fixtures, as his row names it. */
export interface LiveFixture {
  id: number;
  /** The opponent's short name, or null where the calendar does not name the fixture. */
  opponent: string | null;
  kickoff: string | null;
  phase: LivePhase;
  /** His minutes in this fixture, where the read says them. */
  minutes: number | null;
}

export interface LiveRow {
  elementId: number;
  /** The table's short name, as the member page names the player. */
  name: string;
  /** The full name, for the shirt's initials. */
  fullName: string;
  /** The club's name as the table states it. */
  team: string;
  /** The club's short name as the calendar states it, or null. */
  code: string | null;
  position: Position;
  /** 1 to 15, the member's own order. */
  pick: number;
  group: LiveGroup;
  /** Where his current fixture stands; null for a club with no fixture this week. */
  phase: LivePhase | null;
  fixture: LiveFixture | null;
  fixtures: LiveFixture[];
  /** Whether any of his fixtures has kicked off; before it his points are a dash. */
  started: boolean;
  points: number;
  minutes: number;
  goals: number;
  assists: number;
  card: boolean;
  multiplier: Multiplier;
  counted: boolean;
  armband: "captain" | "vice" | null;
  autosub: "in" | "out" | null;
  /** FPL's points less appearance points, or null where no state is drawn. */
  net: number | null;
  state: LiveState | null;
  fact: LiveFact | null;
}

export interface LiveBoard {
  entryId: number;
  season: string;
  gameweek: number;
  sourceTime: string;
  chip: MemberWeek["active_chip"];
  /** The official score, net of the transfer cost, and before it. */
  net: number;
  gross: number;
  transferCost: number;
  /** The week's fixtures that are over (FPL's finished, or past the window), and all of them. */
  matchesOver: number;
  matchesTotal: number;
  /** Every fixture finished by FPL: the bonus is in, and nothing is left to read. */
  final: boolean;
  /** One of the week's fixtures is being played at the read's source time. */
  inPlay: boolean;
  captain: number | null;
  /** The fifteen in the member's order. */
  rows: LiveRow[];
  groups: Record<LiveGroup, LiveRow[]>;
  doingWell: number;
  struggling: number;
  /** Counted picks with a fixture still to finish. */
  left: number;
}

export interface LiveBoardInput {
  live: WeekLive;
  activity: LiveActivity | null;
  member: MemberWeek;
  table: DevicePlanDocument;
  fixtures: FixturesPayload;
}

/** What an appearance alone gives: none for no minutes, one under sixty, two from sixty. */
export function appearancePoints(minutes: number): number {
  return minutes <= 0 ? 0 : minutes < 60 ? 1 : 2;
}

/** The state of a net: one or more is up, minus one or less is down. */
export function stateOf(net: number): LiveState {
  return net >= 1 ? "up" : net <= -1 ? "down" : "neutral";
}

const instant = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
};

/** The calendar's fixtures by id, and its clubs' short names by id. */
function calendarIndex(fixtures: FixturesPayload) {
  const byId = new Map<number, Fixture>();
  const codes = new Map<number, string>();
  for (const week of fixtures.gameweeks) {
    for (const fixture of week.fixtures) {
      byId.set(fixture.fixture_id, fixture);
      codes.set(fixture.home.team_id, fixture.home.short_name);
      codes.set(fixture.away.team_id, fixture.away.short_name);
    }
  }
  return { byId, codes };
}

/** Kickoff first, a fixture with no date last, then by id. */
const byKickoff = (a: LiveFixture, b: LiveFixture) =>
  (instant(a.kickoff) ?? Number.POSITIVE_INFINITY) -
    (instant(b.kickoff) ?? Number.POSITIVE_INFINITY) || a.id - b.id;

/** The board, or null where the scorer, the table or the calendar cannot score the week. */
export function liveBoard(input: LiveBoardInput): LiveBoard | null {
  const { live, activity, member, table, fixtures } = input;
  const result = memberLiveScore({ live, activity, member, table, fixtures });
  if (!result.ok) return null;
  const { score, names } = result.live;
  const clubIds = forecastSource(fixtures)!.club_ids_by_name;
  const calendar = calendarIndex(fixtures);
  const players = new Map(table.players.map((player) => [player.element_id, player]));
  const elements = new Map(live.elements.map((element) => [element.element_id, element]));
  const time = Date.parse(live.source_time);
  const inPlay = new Set(activity?.in_play_fixtures ?? []);
  const appearances = new Map<string, { minutes: number; goals: number; assists: number }>();
  for (const row of activity?.appearances ?? []) {
    appearances.set(`${row.element_id}:${row.fixture_id}`, row);
  }

  /** A fixture's phase at the read's time; a pick's own minutes in it mean it has started. */
  const phaseOf = (fixture: WeekLive["fixtures"][number], minutes: number | null): LivePhase => {
    const kickoff = instant(calendar.byId.get(fixture.id)?.kickoff_utc);
    if (fixture.finished || (kickoff !== null && time >= kickoff + MATCH_WINDOW_MS)) {
      return "finished";
    }
    const started =
      activity !== null ? inPlay.has(fixture.id) : kickoff !== null && time >= kickoff;
    return started || (minutes ?? 0) > 0 ? "playing" : "upcoming";
  };

  const counted = new Set(score.counted);
  const armbandHolder = score.captain ?? member.captain;
  const outs = new Set(score.autosubs.map(([out]) => out));
  const ins = new Set(score.autosubs.map(([, incoming]) => incoming));

  const rows = member.pick_order.map((elementId, index): LiveRow => {
    const element = elements.get(elementId)!;
    const player = players.get(elementId)!;
    const club = clubIds.get(player.team)!;
    const own = live.fixtures.filter(
      (fixture) => fixture.home_club === club || fixture.away_club === club,
    );
    const double = own.length > 1;
    const list = own
      .map((fixture): LiveFixture => {
        const known = calendar.byId.get(fixture.id);
        const opponent = fixture.home_club === club ? fixture.away_club : fixture.home_club;
        const minutes =
          activity !== null
            ? (appearances.get(`${elementId}:${fixture.id}`)?.minutes ?? 0)
            : double
              ? null
              : element.minutes;
        return {
          id: fixture.id,
          opponent: calendar.codes.get(opponent) ?? null,
          kickoff: known?.kickoff_utc ?? null,
          phase: phaseOf(fixture, minutes),
          minutes,
        };
      })
      .sort(byKickoff);
    const current =
      list.find((fixture) => fixture.phase === "playing") ??
      list.find((fixture) => fixture.phase === "upcoming") ??
      list.at(-1) ??
      null;
    const started = list.some((fixture) => fixture.phase !== "upcoming");
    const complete = own.length > 0 && own.every((fixture) => fixture.finished);
    let goals = 0;
    let assists = 0;
    for (const fixture of own) {
      const row = appearances.get(`${elementId}:${fixture.id}`);
      goals += row?.goals ?? 0;
      assists += row?.assists ?? 0;
    }
    const multiplier: Multiplier = !counted.has(elementId)
      ? 0
      : elementId === score.captain
        ? member.active_chip === "3xc"
          ? 3
          : 2
        : 1;
    // A double week's state needs each fixture's minutes; a pick with nothing to show has none.
    const minutesEach = list.map((fixture) => fixture.minutes);
    const quiet = element.minutes === 0 && !element.card_shown && element.points === 0;
    const net =
      !started || list.length === 0 || quiet || minutesEach.some((minutes) => minutes === null)
        ? null
        : element.points -
          minutesEach.reduce<number>((sum, minutes) => sum + appearancePoints(minutes ?? 0), 0);
    return {
      elementId,
      name: names.get(elementId) ?? player.name,
      fullName: player.name,
      team: player.team,
      code: calendar.codes.get(club) ?? null,
      position: player.position as Position,
      pick: index + 1,
      group: index >= 11 ? "bench" : (current?.phase ?? "finished"),
      phase: current?.phase ?? null,
      fixture: current,
      fixtures: list,
      started,
      points: element.points,
      minutes: element.minutes,
      goals,
      assists,
      card: element.card_shown,
      multiplier,
      counted: multiplier > 0,
      armband:
        elementId === armbandHolder
          ? "captain"
          : elementId === member.vice && armbandHolder !== member.vice
            ? "vice"
            : null,
      autosub: outs.has(elementId) ? "out" : ins.has(elementId) ? "in" : null,
      net,
      state: net === null ? null : stateOf(net),
      fact:
        own.length === 0
          ? "noMatch"
          : complete && element.minutes === 0 && !element.card_shown
            ? "didNotPlay"
            : null,
    };
  });

  const groups: Record<LiveGroup, LiveRow[]> = {
    playing: [],
    upcoming: [],
    finished: [],
    bench: [],
  };
  for (const row of rows) groups[row.group].push(row);
  // Within a match group the armband's holder stands first, then the member's order.
  for (const group of ["playing", "upcoming", "finished"] as const) {
    groups[group].sort(
      (a, b) =>
        Number(b.armband === "captain") - Number(a.armband === "captain") || a.pick - b.pick,
    );
  }
  const over = live.fixtures.filter((fixture) => phaseOf(fixture, null) === "finished").length;
  return {
    entryId: member.entry_id,
    season: live.season,
    gameweek: live.gameweek,
    sourceTime: live.source_time,
    chip: member.active_chip,
    net: score.net,
    gross: score.gross,
    transferCost: score.transfer_cost,
    matchesOver: over,
    matchesTotal: live.fixtures.length,
    final: score.bonus_confirmed,
    inPlay: live.fixtures.some((fixture) => phaseOf(fixture, null) === "playing"),
    captain: score.captain,
    rows,
    groups,
    doingWell: rows.filter((row) => row.counted && row.state === "up").length,
    struggling: rows.filter((row) => row.counted && row.state === "down").length,
    left: rows.filter(
      (row) => row.counted && row.fixtures.some((fixture) => fixture.phase !== "finished"),
    ).length,
  };
}

/** The points a row adds to the member's score, or its own points where it does not count. */
export function rowPoints(row: LiveRow): number {
  return row.points * Math.max(row.multiplier, 1);
}

/** One row of "Son bakıştan beri": what a newer read added for one pick. */
export interface RecapItem {
  elementId: number;
  name: string;
  goals: number;
  assists: number;
  card: boolean;
  /** The change in the row's points, as the row shows them. */
  change: number;
}

/** At most this many rows of the recap are shown. */
export const RECAP_ROWS = 6;

/**
 * What a newer read of the same member's week changed against the board shown before it:
 * the goals, assists and cards it added and each row's change in points, the biggest first.
 * Nothing for a first read, another member or week, or a read that is not newer.
 */
export function liveRecap(previous: LiveBoard | null, next: LiveBoard): RecapItem[] {
  if (
    previous === null ||
    previous.entryId !== next.entryId ||
    previous.gameweek !== next.gameweek ||
    !(Date.parse(next.sourceTime) > Date.parse(previous.sourceTime))
  ) {
    return [];
  }
  const before = new Map(previous.rows.map((row) => [row.elementId, row]));
  const items: (RecapItem & { pick: number })[] = [];
  for (const row of next.rows) {
    const old = before.get(row.elementId);
    if (old === undefined) continue;
    const item = {
      elementId: row.elementId,
      name: row.name,
      goals: Math.max(row.goals - old.goals, 0),
      assists: Math.max(row.assists - old.assists, 0),
      card: row.card && !old.card,
      change: rowPoints(row) - rowPoints(old),
      pick: row.pick,
    };
    if (item.goals > 0 || item.assists > 0 || item.card || item.change !== 0) items.push(item);
  }
  return items
    .sort((a, b) => Math.abs(b.change) - Math.abs(a.change) || a.pick - b.pick)
    .slice(0, RECAP_ROWS)
    .map(({ pick: _pick, ...item }) => item);
}
