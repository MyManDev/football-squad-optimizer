/**
 * Synthetic documents of the FPL forwarder (ADR 0012) and what the member page reads beside
 * them, for tests and the e2e specs. The forwarder's documents are its contracts' own
 * examples (`docs/contracts/*.examples.json`); the capture's table and the calendar name the
 * same invented players and clubs. Never a member capture.
 */

import standingsExamples from "../../../docs/contracts/fpl_league_standings_v1.examples.json" with { type: "json" };
import bundleExamples from "../../../docs/contracts/fpl_entry_bundle_v1.examples.json" with { type: "json" };
import liveExamples from "../../../docs/contracts/week_live_v1.examples.json" with { type: "json" };
import deviceInstances from "./device-plan/instances.json" with { type: "json" };
import type { FixturesPayload } from "../features/fixtures/types";
import type { FplEntryBundle } from "../features/league/forwarder/documents";
import type { DevicePlanDocument } from "../features/league/device/types";
import type { MemberWeek, WeekLive } from "../features/liveScore/weekLive";

export const STANDINGS_EXAMPLES = standingsExamples;
export const BUNDLE_EXAMPLES = bundleExamples as unknown as Record<
  "free_hit_walk_back" | "late_joiner",
  FplEntryBundle
>;

export type LiveExample = keyof typeof liveExamples;

/** The `week_live_v1` examples as the contract states them: positions, clubs and a member. */
export const LIVE_EXAMPLES = liveExamples as unknown as Record<LiveExample, WeekLive>;

const clone = <T>(value: T): T => structuredClone(value);

/**
 * A `week_live_v1` example as the forwarder serves it: for `gameweek`, without member blocks
 * and without positions or clubs, which the page resolves from the capture's table.
 */
export function forwardedLive(name: LiveExample, gameweek: number): WeekLive {
  const { members: _members, ...document } = clone(liveExamples[name]);
  return {
    ...(document as Omit<WeekLive, "gameweek" | "elements">),
    contract_version: "week_live_v1",
    gameweek,
    elements: document.elements.map(({ position: _position, club: _club, ...element }) => element),
  };
}

/** The example's member block, as the entry's current week of `gameweek`. */
export function exampleMember(entryId: number, gameweek: number): MemberWeek {
  return {
    ...(clone(liveExamples.in_progress.members[0]) as MemberWeek),
    entry_id: entryId,
    gameweek,
  };
}

/** The example's clubs by id, as the calendar names them. */
export const EXAMPLE_CLUBS = [1, 2, 3, 4, 5, 6].map((id) => ({
  team_id: id,
  name: `Club ${id}`,
  short_name: `C${id}`,
}));

/** The example's fifteen players by element id, as the capture's table names them. */
export const EXAMPLE_NAMES = new Map(
  liveExamples.in_progress.elements.map((element) => [
    element.element_id,
    `Player ${element.element_id}`,
  ]),
);

/**
 * A capture's table (`league_device_plan_v2`) that names the example's fifteen: each one's
 * element id, position and club as the example states them, and a persistent id of its own.
 */
export function exampleTable({
  season,
  gameweek,
  capture,
}: {
  season: string;
  gameweek: number;
  capture: string;
}): DevicePlanDocument {
  return {
    contract_version: "league_device_plan_v2",
    season,
    gameweek,
    source_snapshot_id: capture,
    policy_id: "member_planning_policy_v2",
    rules: {
      squad_size: 15,
      starting_size: 11,
      squad_position_limits: { GK: 2, DEF: 5, MID: 5, FWD: 3 },
      starting_position_min: { GK: 1, DEF: 3, MID: 2, FWD: 1 },
      starting_position_max: { GK: 1, DEF: 5, MID: 5, FWD: 3 },
      max_players_per_team: 3,
      max_free_transfers: 5,
      hit_cost_scaled: 8000,
      hit_points_charged: 4,
      expected_points_scale: 1000,
      chips: [],
      transfers_cap: null,
    },
    players: liveExamples.in_progress.elements.map((element) => ({
      id: 9000 + element.element_id,
      element_id: element.element_id,
      name: `Player ${element.element_id}`,
      short_name: `Player ${element.element_id}`,
      team: `Club ${element.club}`,
      position: element.position,
      buy_tenths: 50,
      start_tenths: 50,
      expected_points: 2,
      coefficients: [200, 1800, 2000],
    })),
  };
}

/**
 * The site's calendar for `gameweek`, its deadline at `deadline`, with the example's three
 * fixtures between its six clubs.
 */
export function exampleCalendar({
  season,
  gameweek,
  deadline,
}: {
  season: string;
  gameweek: number;
  deadline: string;
}): FixturesPayload {
  const fixture = (id: number, home: number, away: number) => ({
    fixture_id: id,
    kickoff_utc: deadline,
    home: EXAMPLE_CLUBS[home - 1]!,
    away: EXAMPLE_CLUBS[away - 1]!,
    finished: false,
    home_score: null,
    away_score: null,
  });
  return {
    season,
    source_snapshot_id: "synthetic-calendar",
    captured_at_utc: deadline,
    current_gameweek: gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek,
        deadline_utc: deadline,
        fixtures: [fixture(61, 1, 2), fixture(62, 3, 4), fixture(63, 5, 6)],
      },
    ],
  };
}

/**
 * A bundle for `entryId` at table gameweek `gameweek`: an entry from gameweek 1 that has
 * made no transfer, holding the example's fifteen, with `current` as its current week.
 */
export function exampleBundle(
  entryId: number,
  gameweek: number,
  current: MemberWeek | null,
): FplEntryBundle {
  const order = liveExamples.in_progress.members[0]!.pick_order;
  const weeks = Array.from({ length: gameweek - 1 }, (_, index) => index + 1);
  return {
    contract_version: "fpl_entry_bundle_v1",
    entry_id: entryId,
    gameweek,
    source_time: "2026-10-10T20:00:00Z",
    entry: { id: entryId, name: "Synthetic XI", started_event: 1 },
    history: {
      current: weeks.map((event) => ({
        event,
        event_transfers: 0,
        event_transfers_cost: 0,
        bank: 0,
      })),
      chips: [],
    },
    transfers: [],
    picks: [...new Set([1, gameweek - 1])].map((event) => ({
      active_chip: null,
      automatic_subs: [],
      entry_history: { event, bank: 0, value: 1000 },
      picks: order.map((element, index) => ({
        element,
        position: index + 1,
        multiplier: element === 7 ? 2 : index < 11 ? 1 : 0,
        is_captain: element === 7,
        is_vice_captain: element === 8,
      })),
    })),
    current_week: current,
  };
}

/**
 * The device-plan parity fixture's table as a capture's own table (`league_device_plan_v2`):
 * no league, each player's element id his persistent id and his start price his price now,
 * no chip windows and no weekly transfer cap.
 */
export function fixtureCaptureTable(capture: string): DevicePlanDocument {
  const { league_id: _league, ...shared } = clone(
    deviceInstances.document,
  ) as unknown as DevicePlanDocument & { league_id: number };
  return {
    ...shared,
    contract_version: "league_device_plan_v2",
    source_snapshot_id: capture,
    rules: { ...shared.rules, chips: [], transfers_cap: null },
    players: shared.players.map((player) => ({
      ...player,
      element_id: player.id,
      start_tenths: player.buy_tenths,
    })),
  };
}

/**
 * A bundle at table gameweek `gameweek` for an entry from gameweek 1 that has made no
 * transfer and holds `fifteen` (element ids, the first eleven starting) with `bank` in the
 * bank and the picks' stated worth `value`, `captain` and `vice` wearing the armbands.
 */
export function bundleHolding(
  entryId: number,
  gameweek: number,
  fifteen: readonly number[],
  {
    bank,
    value,
    captain,
    vice,
    name = "Synthetic XI",
  }: { bank: number; value: number; captain: number; vice: number; name?: string },
): FplEntryBundle {
  const weeks = Array.from({ length: gameweek - 1 }, (_, index) => index + 1);
  return {
    contract_version: "fpl_entry_bundle_v1",
    entry_id: entryId,
    gameweek,
    source_time: "2026-10-10T20:00:00Z",
    entry: { id: entryId, name, started_event: 1 },
    history: {
      current: weeks.map((event) => ({
        event,
        event_transfers: 0,
        event_transfers_cost: 0,
        bank,
      })),
      chips: [],
    },
    transfers: [],
    picks: [...new Set([1, gameweek - 1])].map((event) => ({
      active_chip: null,
      automatic_subs: [],
      entry_history: { event, bank, value },
      picks: fifteen.map((element, index) => ({
        element,
        position: index + 1,
        multiplier: element === captain ? 2 : index < 11 ? 1 : 0,
        is_captain: element === captain,
        is_vice_captain: element === vice,
      })),
    })),
    current_week: null,
  };
}
