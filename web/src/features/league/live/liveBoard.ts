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
  /** His goals and assists in this fixture: none where the read has no event detail. */
  goals: number;
  assists: number;
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
  /** The read had event detail: its goals and assists are FPL's, not a read's lack of them. */
  detailed: boolean;
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

/**
 * What the member's score takes of a pick's points, as the official scorer decides it: none
 * for a pick it does not count, the armband's two (three under the triple captain) for the
 * captain it names, else once.
 */
export function pickMultiplier(
  elementId: number,
  counted: ReadonlySet<number>,
  captain: number | null,
  chip: MemberWeek["active_chip"],
): Multiplier {
  if (!counted.has(elementId)) return 0;
  if (elementId !== captain) return 1;
  return chip === "3xc" ? 3 : 2;
}

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

  // The fixtures someone has played minutes in, where the read has detail; where it has none,
  // the clubs someone has played for in the week.
  const playedIn = new Set<number>();
  for (const row of activity?.appearances ?? []) if (row.minutes > 0) playedIn.add(row.fixture_id);
  const clubsPlayed = new Set<number>();
  if (activity === null) {
    for (const element of live.elements) {
      const team = element.minutes > 0 ? players.get(element.element_id)?.team : undefined;
      const club = team === undefined ? undefined : clubIds.get(team);
      if (club !== undefined) clubsPlayed.add(club);
    }
  }

  /**
   * A fixture's phase at the read's time. A match has started once FPL lists it in play or
   * someone has played in it (with no detail: its kickoff has passed and someone has played for
   * one of its clubs), and past its window only a match that started is over; one that never did
   * (put back, or moved within the day) is still to come. A pick's own minutes in it mean it has
   * started. The window still ends a started match: FPL lists a match in play until its bonus is
   * checked, an hour or more after the final whistle.
   */
  const phaseOf = (fixture: WeekLive["fixtures"][number], minutes: number | null): LivePhase => {
    const kickoff = instant(calendar.byId.get(fixture.id)?.kickoff_utc);
    const started =
      (activity !== null
        ? inPlay.has(fixture.id) || playedIn.has(fixture.id)
        : kickoff !== null &&
          time >= kickoff &&
          (clubsPlayed.has(fixture.home_club) || clubsPlayed.has(fixture.away_club))) ||
      (minutes ?? 0) > 0;
    if (fixture.finished) return "finished";
    if (kickoff !== null && time >= kickoff + MATCH_WINDOW_MS) {
      return started ? "finished" : "upcoming";
    }
    return started ? "playing" : "upcoming";
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
        const detail = appearances.get(`${elementId}:${fixture.id}`);
        return {
          id: fixture.id,
          opponent: calendar.codes.get(opponent) ?? null,
          kickoff: known?.kickoff_utc ?? null,
          phase: phaseOf(fixture, minutes),
          minutes,
          goals: detail?.goals ?? 0,
          assists: detail?.assists ?? 0,
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
    const goals = list.reduce((sum, fixture) => sum + fixture.goals, 0);
    const assists = list.reduce((sum, fixture) => sum + fixture.assists, 0);
    const multiplier = pickMultiplier(elementId, counted, score.captain, member.active_chip);
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
    detailed: activity !== null,
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

/** The points a row shows: what the member's score takes, or his own where it takes none. */
export function rowPoints(row: LiveRow): number {
  return row.points * Math.max(row.multiplier, 1);
}

/** What a row brings the member's score: his points times its multiplier, none uncounted. */
export function rowTake(row: LiveRow): number {
  return row.points * row.multiplier;
}

/** One row of "Son bakıştan beri": what the reads since the last look brought one pick. */
export interface RecapItem {
  elementId: number;
  name: string;
  goals: number;
  assists: number;
  card: boolean;
  /** The change in what the member's score takes of him. */
  change: number;
}

/** At most this many rows of the recap are shown. */
export const RECAP_ROWS = 6;

/**
 * "Son bakıştan beri" (the owner's word of 2026-11-11: show the players the member gets
 * points from in that match, a reserve only under the bench boost): what the reads since the
 * visitor last looked changed in what the member's score takes of each pick, and the goals,
 * assists and cards of the picks it counts.
 *
 * - The change is points times the scorer's multiplier, so a reserve the scorer does not
 *   count changes nothing, and the read that brings him on adds his points.
 * - Goals and assists are high-water marks per pick and fixture, as the GOL board keeps
 *   them: a read without event detail keeps the marks it had, and while no read has had
 *   detail, the first one that has it is only a starting point.
 * - Each newer read adds to what is held, pick by pick, until the visitor looks again
 *   (`lookedAt`); a read that changes nothing leaves it as it was.
 */
export interface LiveRecap {
  /** The member and week the recap belongs to; another starts afresh. */
  identity: string;
  /** The source time of the newest board taken in, in milliseconds. */
  time: number;
  /** What the member's score takes of each pick, at the newest board. */
  takes: ReadonlyMap<number, number>;
  /** The highest goals and assists seen, keyed `element:fixture:kind`. */
  counts: ReadonlyMap<string, number>;
  /** Whether a board taken in had event detail, so `counts` is a starting point. */
  detailed: boolean;
  /** The picks a card has been shown to. */
  cards: ReadonlySet<number>;
  /** What changed since the last look, by pick. */
  items: ReadonlyMap<number, RecapItem & { pick: number }>;
  /**
   * The goals, assists and cards the newest board added, by pick: only those the member's score
   * takes, as the items tell them. What LIVE's rows move for.
   */
  fresh: ReadonlyMap<number, LiveEvents>;
}

/** The events one board added to a pick. */
export interface LiveEvents {
  goals: number;
  assists: number;
  card: boolean;
}

/**
 * The marks a recap counts against, as a look keeps them for the visitor's next visit: what is
 * new since is told then, its items starting empty.
 */
export type RecapMarks = Pick<
  LiveRecap,
  "identity" | "time" | "takes" | "counts" | "detailed" | "cards"
>;

/** The recap that counts from `marks`, nothing told yet. */
export function recapFrom(marks: RecapMarks): LiveRecap {
  return { ...marks, items: new Map(), fresh: new Map() };
}

/** The recap with `board` taken in: the first board of a member's week is a starting point. */
export function advanceRecap(recap: LiveRecap | null, board: LiveBoard): LiveRecap {
  const identity = `${board.entryId}:${board.gameweek}`;
  const time = Date.parse(board.sourceTime);
  const same = recap !== null && recap.identity === identity;
  if (same && !(time > recap.time)) return recap;
  const takes = new Map<number, number>();
  const counts = new Map(same ? recap.counts : []);
  const cards = new Set(same ? recap.cards : []);
  const items = new Map(same ? recap.items : []);
  const fresh = new Map<number, LiveEvents>();
  // Goals and assists are counted only against marks a board with detail set.
  const counting = same && recap.detailed;
  for (const row of board.rows) {
    const take = rowTake(row);
    takes.set(row.elementId, take);
    let goals = 0;
    let assists = 0;
    if (board.detailed) {
      for (const fixture of row.fixtures) {
        const goalKey = `${row.elementId}:${fixture.id}:goal`;
        const assistKey = `${row.elementId}:${fixture.id}:assist`;
        const seenGoals = counts.get(goalKey) ?? 0;
        const seenAssists = counts.get(assistKey) ?? 0;
        if (counting) {
          goals += Math.max(fixture.goals - seenGoals, 0);
          assists += Math.max(fixture.assists - seenAssists, 0);
        }
        counts.set(goalKey, Math.max(seenGoals, fixture.goals));
        counts.set(assistKey, Math.max(seenAssists, fixture.assists));
      }
    }
    const card = same && row.card && !cards.has(row.elementId);
    if (row.card) cards.add(row.elementId);
    if (!same) continue;
    const change = take - (recap.takes.get(row.elementId) ?? take);
    // Only what the member's score takes is told: a pick it does not count tells no event.
    const told = row.multiplier > 0;
    if (told && (goals > 0 || assists > 0 || card)) {
      fresh.set(row.elementId, { goals, assists, card });
    }
    if (change === 0 && !(told && (goals > 0 || assists > 0 || card))) continue;
    const before = items.get(row.elementId);
    const merged = {
      elementId: row.elementId,
      name: row.name,
      pick: row.pick,
      goals: (before?.goals ?? 0) + (told ? goals : 0),
      assists: (before?.assists ?? 0) + (told ? assists : 0),
      card: (before?.card ?? false) || (told && card),
      change: (before?.change ?? 0) + change,
    };
    if (merged.change === 0 && merged.goals === 0 && merged.assists === 0 && !merged.card) {
      items.delete(row.elementId);
    } else {
      items.set(row.elementId, merged);
    }
  }
  return {
    identity,
    time,
    takes,
    counts,
    detailed: (same && recap.detailed) || board.detailed,
    cards,
    items,
    fresh,
  };
}

/** The visitor has looked: what the recap holds is told, its marks stay. */
export function lookedAt(recap: LiveRecap | null): LiveRecap | null {
  return recap === null || recap.items.size === 0 ? recap : { ...recap, items: new Map() };
}

/** The recap's rows, the biggest change first, at most `RECAP_ROWS`. */
export function recapItems(recap: LiveRecap | null): RecapItem[] {
  if (recap === null) return [];
  return [...recap.items.values()]
    .sort(
      (a, b) =>
        Math.abs(b.change) - Math.abs(a.change) ||
        b.goals + b.assists - (a.goals + a.assists) ||
        a.pick - b.pick,
    )
    .slice(0, RECAP_ROWS)
    .map(({ pick: _pick, ...item }) => item);
}
