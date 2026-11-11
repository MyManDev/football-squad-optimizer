import { createHash } from "node:crypto";

import type { Page } from "@playwright/test";

import {
  bundleHolding,
  exampleCalendar,
  exampleTable,
  fixtureCaptureTable,
} from "../src/fixtures/forwarder";
import { mockEntrySquadEnvelopes, mockLeagueMembersEnvelope } from "../src/fixtures/league";
import type { FixturesPayload } from "../src/features/fixtures/types";
import type { FplEntryBundle, FplEntrySeason } from "../src/features/league/forwarder/documents";
import type { WeekActivity } from "../src/features/liveScore/weekActivity";
import type { MemberWeek } from "../src/features/liveScore/weekLive";
import { installLeagueMocks } from "./leagueMocks";
import type { SeededClaim } from "./identity";

/**
 * The live week's mocks the member page's and the LIVE page's specs share: the published
 * example league with a closed week, the forwarder's marked answers, and a forwarded week of
 * the device-plan parity table's players for the leagues and teams the site does not publish.
 * Every document is synthetic.
 */

export const MARKED = { "x-squadopt-fpl": "1", "content-type": "application/json; charset=utf-8" };

export function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

/** The published example league's first member and his squad's week and capture. */
export const LISTED_ENTRY = 35249001;
export const LISTED = mockEntrySquadEnvelopes[LISTED_ENTRY]!.payload;
const LISTED_TABLE_PATH = `device/${LISTED.source_snapshot_id}/device-plan.json`;

function envelope(payload: unknown, contract = "provisional_league_ui_v1") {
  return {
    contract_version: contract,
    generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
    source_kind: "live",
    payload,
  };
}

/** The league with a closed week, the capture's table its directory line names, and the calendar. */
export async function closedWeek(page: Page, calendar?: FixturesPayload) {
  await installLeagueMocks(page);
  const { league_id, league_name } = mockLeagueMembersEnvelope.payload;
  const { season, gameweek } = LISTED;
  const bytes = `${JSON.stringify(
    envelope(exampleTable({ season, gameweek, capture: LISTED.source_snapshot_id! })),
  )}\n`;
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "league_directory_v1",
        generated_at_utc: mockLeagueMembersEnvelope.generated_at_utc,
        source_kind: "live",
        payload: {
          leagues: [
            {
              league_id,
              league_name,
              season,
              gameweek,
              path: "league",
              device_plan: LISTED_TABLE_PATH,
              device_plan_sha256: sha256(bytes),
            },
          ],
        },
      }),
    }),
  );
  await page.route(/\/data\/device\//, (route) =>
    route.fulfill({ contentType: "application/json", body: bytes }),
  );
  await serveCalendar(
    page,
    calendar ?? exampleCalendar({ season, gameweek, deadline: "2020-01-01T00:00:00Z" }),
  );
}

export async function serveCalendar(page: Page, calendar: FixturesPayload) {
  await page.route("**/data/fixtures.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(envelope(calendar, "fixtures_v1")),
    }),
  );
}

/**
 * The example's calendar for `gameweek` with each of its three fixtures at its own kickoff
 * (61 to 63), the deadline 90 minutes before the first.
 */
export function exampleWeek(
  gameweek: number,
  kickoffs: [string, string, string],
  later: { gameweek: number; deadline: string }[] = [],
): FixturesPayload {
  const deadline = new Date(Date.parse(kickoffs[0]) - 90 * 60_000).toISOString();
  const calendar = exampleCalendar({ season: LISTED.season, gameweek, deadline });
  calendar.gameweeks[0]!.fixtures.forEach((fixture, index) => {
    fixture.kickoff_utc = kickoffs[index]!;
  });
  calendar.gameweeks.push(
    ...later.map((week) => ({
      gameweek: week.gameweek,
      deadline_utc: week.deadline,
      fixtures: [],
    })),
  );
  return calendar;
}

/** One entry's season to date: `total` points after each played week before `gameweek`. */
export function seasonOf(entryId: number, gameweek: number, perWeek: number): FplEntrySeason {
  return {
    contract_version: "fpl_entry_season_v1",
    entry_id: entryId,
    source_time: "2026-11-21T12:00:00Z",
    weeks: Array.from({ length: gameweek - 1 }, (_, index) => ({
      event: index + 1,
      points: perWeek,
      total_points: perWeek * (index + 1),
      rank: null,
      overall_rank: null,
      event_transfers: 0,
      event_transfers_cost: 0,
      bank: 0,
      value: 1000,
    })),
    chips: [],
  };
}

/* ---- A forwarded week: the parity table's sixty players in eight clubs ---- */

/** The capture the directory names for the forwarded pages, and its table. */
export const FORWARDED_CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
export const FORWARDED_TABLE = fixtureCaptureTable(FORWARDED_CAPTURE);
/** The parity fixture member's fifteen, the first eleven a legal formation. */
export const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];

const clubOf = (team: string) => Number(team.replace("Club ", ""));
const CLUBS = Array.from({ length: 8 }, (_, index) => ({
  team_id: index + 1,
  name: `Club ${index + 1}`,
  short_name: `K${index + 1}`,
}));

/** The live week's four fixtures: one finished, two being played and one to come. */
export function forwardedFixtures(kickoff: number) {
  const at = (minutes: number) => new Date(kickoff + minutes * 60_000).toISOString();
  return [
    { id: 71, home: 1, away: 2, kickoff: at(-150), finished: true },
    { id: 72, home: 3, away: 4, kickoff: at(0), finished: false },
    { id: 73, home: 5, away: 6, kickoff: at(0), finished: false },
    { id: 74, home: 7, away: 8, kickoff: at(150), finished: false },
  ];
}

/** The site's calendar for a forwarded week, `later` weeks after it with open deadlines. */
export function forwardedCalendar(
  gameweek: number,
  kickoff: number,
  later: { gameweek: number; deadline: string }[] = [],
): FixturesPayload {
  const fixtures = forwardedFixtures(kickoff);
  return {
    season: FORWARDED_TABLE.season,
    source_snapshot_id: FORWARDED_CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek,
        deadline_utc: new Date(kickoff - 240 * 60_000).toISOString(),
        fixtures: fixtures.map((fixture) => ({
          fixture_id: fixture.id,
          kickoff_utc: fixture.kickoff,
          home: CLUBS[fixture.home - 1]!,
          away: CLUBS[fixture.away - 1]!,
          finished: fixture.finished,
          home_score: null,
          away_score: null,
        })),
      },
      ...later.map((week) => ({
        gameweek: week.gameweek,
        deadline_utc: week.deadline,
        fixtures: [],
      })),
    ],
  };
}

/**
 * The forwarder's `week_activity_v1` for the forwarded week at `sourceTime`: every player of
 * the table with minutes in the fixtures already played, a few goals, assists and a card.
 */
export function forwardedActivity(
  gameweek: number,
  kickoff: number,
  sourceTime: string,
): WeekActivity {
  const fixtures = forwardedFixtures(kickoff);
  const fixtureOf = (club: number) =>
    fixtures.find((fixture) => fixture.home === club || fixture.away === club)!;
  const elements = FORWARDED_TABLE.players.map((player) => {
    const fixture = fixtureOf(clubOf(player.team));
    const started = fixture.id !== 74;
    const id = player.element_id;
    const minutes = !started || id % 5 === 0 ? 0 : fixture.finished ? 90 : 34 + (id % 30);
    const points = minutes === 0 ? 0 : 1 + (id % 7) - (id % 11 === 0 ? 2 : 0);
    return {
      element_id: id,
      points,
      minutes,
      card_shown: minutes > 0 && id % 11 === 0,
      fixture: fixture.id,
    };
  });
  return {
    contract_version: "week_activity_v1",
    week: {
      contract_version: "week_live_v1",
      season: FORWARDED_TABLE.season,
      gameweek,
      source_time: sourceTime,
      fixtures: fixtures.map((fixture) => ({
        id: fixture.id,
        home_club: fixture.home,
        away_club: fixture.away,
        finished: fixture.finished,
      })),
      elements: elements.map(({ fixture: _fixture, ...element }) => element),
    },
    activity: {
      in_play_fixtures: [72, 73],
      appearances: elements.map((element) => ({
        element_id: element.element_id,
        fixture_id: element.fixture,
        minutes: element.minutes,
        goals: element.points >= 6 ? 1 : 0,
        assists: element.points === 5 ? 1 : 0,
      })),
    },
  };
}

/** A legal fifteen beside the member's: two of his players swapped for others of theirs. */
export function rivalFifteen(): number[] {
  const free = (position: string) =>
    FORWARDED_TABLE.players.find(
      (player) => player.position === position && !FIFTEEN.includes(player.element_id),
    )!.element_id;
  return FIFTEEN.map((id) => (id === 155 ? free("FWD") : id === 136 ? free("MID") : id));
}

/** One forwarded entry's bundle for the table week `gameweek`, its live week `live`. */
export function forwardedBundle(
  entryId: number,
  gameweek: number,
  live: number,
  fifteen: readonly number[],
  current: Partial<MemberWeek> = {},
): FplEntryBundle {
  const bundle = bundleHolding(entryId, gameweek, fifteen, {
    bank: 0,
    value: 1000,
    captain: fifteen[6]!,
    vice: fifteen[8]!,
  });
  return {
    ...bundle,
    current_week: {
      entry_id: entryId,
      gameweek: live,
      pick_order: [...fifteen],
      captain: fifteen[6]!,
      vice: fifteen[8]!,
      active_chip: null,
      transfer_cost: 0,
      ...current,
    },
  };
}

/**
 * A directory naming the published league with the forwarded table (its `gameweek` given),
 * and that table, for the forwarded gates.
 */
export async function forwardedSite(page: Page, claim: SeededClaim | null, gameweek: number) {
  await installLeagueMocks(page, { claim });
  const table = { ...FORWARDED_TABLE, gameweek };
  const bytes = `${JSON.stringify({
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload: table,
  })}\n`;
  const published = mockLeagueMembersEnvelope.payload;
  await page.route("**/data/leagues.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        contract_version: "league_directory_v1",
        generated_at_utc: "2026-10-16T08:00:00Z",
        source_kind: "live",
        payload: {
          leagues: [
            {
              league_id: published.league_id,
              league_name: published.league_name,
              season: published.season,
              gameweek,
              path: "league",
              device_plan: `device/${FORWARDED_CAPTURE}/device-plan.json`,
              device_plan_sha256: sha256(bytes),
            },
          ],
        },
      }),
    }),
  );
  await page.route(/\/data\/device\//, (route) =>
    route.fulfill({ contentType: "application/json", body: bytes }),
  );
}
