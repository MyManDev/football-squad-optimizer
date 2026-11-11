/**
 * The documents the phone bar's LIVE pill reads, served by address for its tests and the app
 * shell's: the calendar with a match `minutes` into its window, the directory naming the
 * parity table's capture, that table, and member 5001's bundle with his live week's fifteen.
 * Every document is synthetic.
 */

import { createHash } from "node:crypto";

import { bundleHolding, fixtureCaptureTable } from "../fixtures/forwarder";
import type { FixturesPayload } from "../features/fixtures/types";
import type { FplEntryBundle } from "../features/league/forwarder/documents";
import { jsonResponse, stubFetchByUrl } from "./fetchByUrl";

export const PILL_CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
export const PILL_TABLE = fixtureCaptureTable(PILL_CAPTURE);
export const PILL_ENTRY = 5001;
/** The parity fixture member's fifteen: clubs 1 to 8. */
export const PILL_FIFTEEN = [
  101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156,
];

export const pillEnvelope = (payload: unknown, contract = "provisional_league_ui_v1") => ({
  contract_version: contract,
  generated_at_utc: "2026-10-16T08:00:00Z",
  source_kind: "live",
  payload,
});

const TABLE_BYTES = JSON.stringify(pillEnvelope(PILL_TABLE));

export const PILL_BUNDLE: FplEntryBundle = {
  ...bundleHolding(PILL_ENTRY, PILL_TABLE.gameweek, PILL_FIFTEEN, {
    bank: 0,
    value: 1000,
    captain: 132,
    vice: 139,
  }),
  current_week: {
    entry_id: PILL_ENTRY,
    gameweek: PILL_TABLE.gameweek,
    pick_order: PILL_FIFTEEN,
    captain: 132,
    vice: 139,
    active_chip: null,
    transfer_cost: 0,
  },
};

const team = (club: number) => ({ team_id: club, name: `Club ${club}`, short_name: `K${club}` });

/**
 * The live week: one match between `home` and `away`, kicked off `minutes` ago, and, when
 * `named`, the matches of clubs 1 to 8 (the parity table's) played hours ago.
 */
export function pillCalendar(home: number, away: number, minutes: number, named = true) {
  const at = (ago: number) => new Date(Date.now() - ago * 60_000).toISOString();
  const match = (id: number, one: number, two: number, ago: number, finished: boolean) => ({
    fixture_id: id,
    kickoff_utc: at(ago),
    home: team(one),
    away: team(two),
    finished,
    home_score: null,
    away_score: null,
  });
  const calendar: FixturesPayload = {
    season: PILL_TABLE.season,
    source_snapshot_id: PILL_CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: PILL_TABLE.gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: PILL_TABLE.gameweek,
        deadline_utc: at(1000),
        fixtures: [
          match(71, home, away, minutes, false),
          ...(named ? [1, 3, 5, 7].map((club) => match(72 + club, club, club + 1, 900, true)) : []),
        ],
      },
    ],
  };
  return calendar;
}

/** A forwarder answer, marked as the forwarder marks its own. */
export function pillMarked(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-squadopt-fpl": "1" },
  });
}

/** The site's four documents for the pill, the bundle answered by `bundle`. */
export function pillSite(
  fixtures: FixturesPayload,
  bundle: () => Response | Promise<Response> = () => pillMarked(PILL_BUNDLE),
) {
  return stubFetchByUrl([
    ["/data/fixtures.json", () => jsonResponse(pillEnvelope(fixtures, "fixtures_v1"))],
    [
      "/data/leagues.json",
      () =>
        jsonResponse(
          pillEnvelope(
            {
              leagues: [
                {
                  league_id: 352490,
                  league_name: "League",
                  season: PILL_TABLE.season,
                  gameweek: PILL_TABLE.gameweek,
                  path: "league",
                  device_plan: `device/${PILL_CAPTURE}/device-plan.json`,
                  device_plan_sha256: createHash("sha256").update(TABLE_BYTES).digest("hex"),
                },
              ],
            },
            "league_directory_v1",
          ),
        ),
    ],
    [/\/data\/device\/[^/]+\/device-plan\.json/, () => new Response(TABLE_BYTES)],
    [`/api/v1/fpl/entry/${PILL_ENTRY}/bundle?gw=${PILL_TABLE.gameweek}`, bundle as () => Response],
  ]);
}

/** The paths a stubbed fetch was asked, in order. */
export const askedPaths = (fetcher: ReturnType<typeof pillSite>) =>
  fetcher.mock.calls.map(([url]) => new URL(url, "http://site").pathname);
