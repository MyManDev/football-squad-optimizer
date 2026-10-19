/**
 * The rule bound to one member and the capture the page already reads, as the publisher
 * binds it (`squadopt/application/chip_forecast_publication.py`): the table's expected
 * points and club names, the member's fifteen, armband and chip windows, and the fixture
 * calendar. No solve and no fetch belongs here; the caller passes only gains the device
 * already solved, and an absent gain is unknown. A refusal removes the reading, never the
 * plan, and carries the publisher's own code.
 */

import { CHIP_HALVES, CHIP_NAMES } from "../../chipShape";
import type { FixturesPayload } from "../../../fixtures/types";
import type { EntrySquad } from "../../types";
import type { DevicePlanDocument, DevicePlanPlayer } from "../types";
import {
  chipForecast,
  MEASURED_RESERVATION,
  MEASURED_THRESHOLD_POLICY,
  PROTOCOL_HOLDING_VALUES,
  type ChipName,
  type GameweekFixtures,
  type HeldChip,
  type SquadRow,
} from "./rule";

/** The publisher's refusal codes, each for the same condition as there. */
export type ForecastRefusal =
  | "capture_mismatch"
  | "calendar_missing"
  | "calendar_unreadable"
  | "fixtures_unscheduled"
  | "calendar_incomplete"
  | "club_roster_missing"
  | "club_roster_incomplete"
  | "chip_history_unknown"
  | "chip_window_unreadable"
  | "squad_projection_missing"
  | "forecast_inputs_unreadable";

export class ForecastUnavailable extends Error {
  readonly reason: ForecastRefusal;

  constructor(reason: ForecastRefusal) {
    super(reason);
    this.name = "ForecastUnavailable";
    this.reason = reason;
  }
}

/**
 * The calendar as the forecast reads it: its capture, and every club it names by name. A
 * calendar whose clubs cannot be read carries no calendar and says why, and is refused
 * where the counts are read, after the capture and the chips, as the publisher refuses it.
 */
export interface ForecastSource {
  snapshot_id: string;
  season: string;
  calendar: FixturesPayload | null;
  /** Club name to club id; empty when the calendar names no club. */
  club_ids_by_name: Map<string, number>;
  unavailable_reason: ForecastRefusal | null;
}

/**
 * The published calendar as a forecast source, or null where the page has none. The
 * publisher takes its club roster from the capture's team list; the calendar the page
 * reads names every club that plays a fixture in the season, which is the same twenty.
 * A club name that names two clubs, or a club under two names, is a calendar the roster
 * cannot be read from, as the publisher refuses a team list whose names repeat.
 */
export function forecastSource(
  fixtures: FixturesPayload | null | undefined,
): ForecastSource | null {
  if (!fixtures) return null;
  const unreadable: ForecastSource = {
    snapshot_id: fixtures.source_snapshot_id,
    season: fixtures.season,
    calendar: null,
    club_ids_by_name: new Map(),
    unavailable_reason: "calendar_unreadable",
  };
  const names = new Map<number, string>();
  for (const week of fixtures.gameweeks) {
    for (const fixture of week.fixtures) {
      for (const team of [fixture.home, fixture.away]) {
        const known = names.get(team.team_id);
        if (known !== undefined && known !== team.name) return unreadable;
        names.set(team.team_id, team.name);
      }
    }
  }
  const ids = new Map([...names].map(([club, name]) => [name, club]));
  if (ids.size !== names.size) return unreadable;
  return { ...unreadable, calendar: fixtures, club_ids_by_name: ids, unavailable_reason: null };
}

/**
 * Each gameweek from `first` to `last` as complete club counts, a blank as an explicit
 * zero. The calendar lists matches, not absent clubs, so every week starts from the whole
 * roster at zero. The roster is every club the calendar names, so a fixture never names a
 * club outside it.
 */
export function calendarCounts(
  source: ForecastSource,
  { first, last }: { first: number; last: number },
): GameweekFixtures[] {
  const calendar = source.calendar;
  if (calendar === null) {
    throw new ForecastUnavailable(source.unavailable_reason ?? "calendar_missing");
  }
  if (calendar.unscheduled_count !== 0) throw new ForecastUnavailable("fixtures_unscheduled");
  const clubs = [...source.club_ids_by_name.values()];
  if (clubs.length === 0) throw new ForecastUnavailable("club_roster_missing");
  const weeks = new Map(calendar.gameweeks.map((week) => [week.gameweek, week]));
  if (weeks.size !== calendar.gameweeks.length)
    throw new ForecastUnavailable("calendar_incomplete");
  const result: GameweekFixtures[] = [];
  for (let number = first; number <= last; number += 1) {
    const week = weeks.get(number);
    if (week === undefined) throw new ForecastUnavailable("calendar_incomplete");
    const counts: Record<number, number> = Object.fromEntries(clubs.map((club) => [club, 0]));
    const seen = new Set<number>();
    for (const fixture of week.fixtures) {
      if (seen.has(fixture.fixture_id)) throw new ForecastUnavailable("calendar_incomplete");
      seen.add(fixture.fixture_id);
      counts[fixture.home.team_id]! += 1;
      counts[fixture.away.team_id]! += 1;
    }
    result.push({ gameweek: number, fixture_count_by_club: counts });
  }
  return result;
}

type ChipBlock = EntrySquad["chips"];

/** The chip's windows that cover `gameweek` and are still unspent. */
function openWindows(chips: NonNullable<ChipBlock>, name: ChipName, gameweek: number) {
  return CHIP_HALVES.flatMap((half) => {
    const window = chips.states[name]?.[half];
    return window != null &&
      window.start_event <= gameweek &&
      gameweek <= window.stop_event &&
      window.state === "available"
      ? [window]
      : [];
  });
}

/**
 * The chips the member holds in `gameweek`, in the game's order, as the publisher's chip
 * menu reads them; null where the history is not known. These are the chips the device
 * solves a gain for, one solve each beside the plain plan.
 */
export function heldChips(chips: ChipBlock, gameweek: number): ChipName[] | null {
  if (chips === undefined || !chips.known) return null;
  const windows = CHIP_NAMES.flatMap((name) =>
    CHIP_HALVES.flatMap((half) => {
      const window = chips.states[name]?.[half];
      return window ? [window] : [];
    }),
  );
  if (windows.some((window) => window.state === "unknown")) return null;
  return CHIP_NAMES.filter((name) => openWindows(chips, name, gameweek).length > 0);
}

/** The chip_forecast_v1 document as the device states it: the rule's, without `limits`. */
export type ChipForecastDocument = ReturnType<typeof chipForecast>;

/** The member index's `chip_forecast` envelope, as the device computes it. */
export interface MemberChipForecast {
  season: string;
  league_id: number;
  entry_id: number;
  gameweek: number;
  source_snapshot_id: string;
  squad_player_ids: number[];
  bench_player_ids: number[];
  status: "available" | "unavailable";
  reason: ForecastRefusal | null;
  forecast: ChipForecastDocument | null;
  calendar_has_structure: boolean | null;
  calendar_range: { first_gameweek: number; last_gameweek: number } | null;
}

export interface MemberChipForecastInputs {
  /** The capture's table, as the page's loader reads it. */
  table: Pick<DevicePlanDocument, "season" | "gameweek" | "source_snapshot_id"> & {
    players: Pick<DevicePlanPlayer, "id" | "team" | "position" | "expected_points">[];
  };
  squad: Pick<
    EntrySquad,
    | "league_id"
    | "season"
    | "gameweek"
    | "entry"
    | "starting_xi"
    | "bench"
    | "chips"
    | "source_snapshot_id"
  >;
  fixtures: FixturesPayload | null | undefined;
  /** This week's gain of each held chip the device solved; absent or null is unknown. */
  gains: Partial<Record<ChipName, number | null>>;
}

function positiveInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new TypeError("A chip window must name its gameweeks.");
  }
  return value;
}

function reading(
  { table, squad, fixtures, gains }: MemberChipForecastInputs,
  ids: number[],
): Pick<MemberChipForecast, "forecast" | "calendar_has_structure" | "calendar_range"> {
  const week = table.gameweek;
  const source = forecastSource(fixtures);
  if (source === null) throw new ForecastUnavailable("calendar_missing");
  if (
    source.snapshot_id !== table.source_snapshot_id ||
    squad.source_snapshot_id !== table.source_snapshot_id ||
    squad.season !== table.season ||
    (source.calendar !== null && source.season !== table.season) ||
    squad.gameweek !== week ||
    (squad.chips !== undefined && squad.chips.gameweek !== week)
  ) {
    throw new ForecastUnavailable("capture_mismatch");
  }
  const held = heldChips(squad.chips, week);
  if (held === null) throw new ForecastUnavailable("chip_history_unknown");
  const chips: HeldChip[] = held.map((name) => {
    const active = openWindows(squad.chips!, name, week);
    if (active.length !== 1) throw new ForecastUnavailable("chip_window_unreadable");
    return {
      name,
      first_gameweek: positiveInteger(active[0]!.start_event),
      last_gameweek: positiveInteger(active[0]!.stop_event),
      gain_this_week: gains[name] ?? null,
    };
  });
  const calendar = calendarCounts(source, {
    first: week,
    last: Math.max(week, ...chips.map((chip) => chip.last_gameweek)),
  });
  const players = new Map(table.players.map((player) => [player.id, player]));
  if (players.size !== table.players.length) {
    throw new ForecastUnavailable("forecast_inputs_unreadable");
  }
  const captains = new Set(
    [...squad.starting_xi, ...squad.bench]
      .filter((player) => player.is_captain)
      .map((player) => player.player_id),
  );
  const rows: SquadRow[] = ids.map((id, index) => {
    const player = players.get(id);
    if (player === undefined) throw new ForecastUnavailable("squad_projection_missing");
    const club = source.club_ids_by_name.get(player.team);
    if (club === undefined) throw new ForecastUnavailable("club_roster_incomplete");
    return {
      player_id: id,
      club_id: club,
      position: player.position as SquadRow["position"],
      expected_points: player.expected_points,
      // The bench is the fifteen after the eleven, in the order the entry lists it.
      bench_order: index >= 11 ? index - 10 : null,
      is_captain: captains.has(id),
    };
  });
  const forecast = chipForecast({
    decision_gameweek: week,
    chips,
    squad: rows,
    calendar,
    holding_values: PROTOCOL_HOLDING_VALUES,
    threshold: MEASURED_THRESHOLD_POLICY,
    reserve: MEASURED_RESERVATION,
  });
  const later = calendar.filter((item) => item.gameweek > week);
  // The counts are complete maps, so a blank is a stated zero and a double a two.
  const structured = later.some((item) =>
    Object.values(item.fixture_count_by_club).some((count) => count !== 1),
  );
  return {
    forecast,
    calendar_has_structure: structured,
    calendar_range:
      later.length > 0
        ? { first_gameweek: later[0]!.gameweek, last_gameweek: later.at(-1)!.gameweek }
        : null,
  };
}

/**
 * One complete reading for one member, or the publisher's refusal code. Gains from another
 * capture or another request are never combined into it: the caller passes the gains of
 * the one request that solved this member's plain plan.
 */
export function memberChipForecast(inputs: MemberChipForecastInputs): MemberChipForecast {
  const { table, squad } = inputs;
  const ids = [...squad.starting_xi, ...squad.bench].map((player) => player.player_id);
  const envelope: MemberChipForecast = {
    season: table.season,
    league_id: squad.league_id,
    entry_id: squad.entry.entry_id,
    gameweek: table.gameweek,
    source_snapshot_id: table.source_snapshot_id,
    squad_player_ids: ids,
    bench_player_ids: ids.slice(11),
    status: "unavailable",
    reason: null,
    forecast: null,
    calendar_has_structure: null,
    calendar_range: null,
  };
  try {
    return { ...envelope, status: "available", ...reading(inputs, ids) };
  } catch (error) {
    // Any other failure, the rule's own input checks included, is an input the reading
    // cannot be stated on, which the publisher codes the same way.
    return {
      ...envelope,
      reason: error instanceof ForecastUnavailable ? error.reason : "forecast_inputs_unreadable",
    };
  }
}
