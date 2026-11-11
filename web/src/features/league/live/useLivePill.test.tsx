/**
 * The phone bar's LIVE pill: the LIVE page's address while one of the member's matches is in
 * its window, else nothing, with nothing read outside a match window and the member's clubs
 * read from the documents the forwarded gate reads.
 */

import { createHash } from "node:crypto";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { bundleHolding, fixtureCaptureTable } from "../../../fixtures/forwarder";
import { jsonResponse, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import type { FixturesPayload } from "../../fixtures/types";
import type { FplEntryBundle } from "../forwarder/documents";
import { memberClubs, useLivePill } from "./useLivePill";

afterEach(() => vi.unstubAllGlobals());

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE = fixtureCaptureTable(CAPTURE);
const ENTRY = 5001;
const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
const TARGET = { entryId: ENTRY, to: `/league/314/members/${ENTRY}/live` };

const envelope = (payload: unknown, contract = "provisional_league_ui_v1") => ({
  contract_version: contract,
  generated_at_utc: "2026-10-16T08:00:00Z",
  source_kind: "live",
  payload,
});
const TABLE_BYTES = JSON.stringify(envelope(TABLE));

const BUNDLE: FplEntryBundle = {
  ...bundleHolding(ENTRY, TABLE.gameweek, FIFTEEN, {
    bank: 0,
    value: 1000,
    captain: 132,
    vice: 139,
  }),
  current_week: {
    entry_id: ENTRY,
    gameweek: TABLE.gameweek,
    pick_order: FIFTEEN,
    captain: 132,
    vice: 139,
    active_chip: null,
    transfer_cost: 0,
  },
};

const team = (club: number) => ({ team_id: club, name: `Club ${club}`, short_name: `K${club}` });

/**
 * The live week: one match between `home` and `away`, kicked off `minutes` ago, and the
 * matches of clubs 1 to 8, the parity table's, played hours ago.
 */
function calendar(home: number, away: number, minutes: number, named = true): FixturesPayload {
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
  return {
    season: TABLE.season,
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: TABLE.gameweek,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: TABLE.gameweek,
        deadline_utc: at(1000),
        fixtures: [
          match(71, home, away, minutes, false),
          ...(named ? [1, 3, 5, 7].map((club) => match(72 + club, club, club + 1, 900, true)) : []),
        ],
      },
    ],
  };
}

function site(fixtures: FixturesPayload, bundle: () => Response = () => marked(BUNDLE)) {
  return stubFetchByUrl([
    ["/data/fixtures.json", () => jsonResponse(envelope(fixtures, "fixtures_v1"))],
    [
      "/data/leagues.json",
      () =>
        jsonResponse(
          envelope(
            {
              leagues: [
                {
                  league_id: 352490,
                  league_name: "League",
                  season: TABLE.season,
                  gameweek: TABLE.gameweek,
                  path: "league",
                  device_plan: `device/${CAPTURE}/device-plan.json`,
                  device_plan_sha256: createHash("sha256").update(TABLE_BYTES).digest("hex"),
                },
              ],
            },
            "league_directory_v1",
          ),
        ),
    ],
    [/\/data\/device\/[^/]+\/device-plan\.json/, () => new Response(TABLE_BYTES)],
    [`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`, bundle],
  ]);
}

function marked(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-squadopt-fpl": "1" },
  });
}

function pill(target: typeof TARGET | null, enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useLivePill(target, enabled), { wrapper });
}

const asked = (fetcher: ReturnType<typeof site>) =>
  fetcher.mock.calls.map(([url]) => new URL(url, "http://site").pathname);

describe("the member's clubs", () => {
  it("are the clubs of the live week's picks, by the table's names and the calendar's ids", () => {
    const read = { ok: true as const, copy: null, document: BUNDLE };
    expect([...memberClubs(read, TABLE, calendar(9, 10, 30))!].sort()).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8,
    ]);
    // A calendar that does not name a pick's club cannot say them.
    expect(memberClubs(read, TABLE, calendar(1, 2, 30, false))).toBeNull();
  });

  it("are not known from a bundle without the live week", () => {
    expect(
      memberClubs(
        { ok: true, copy: null, document: { ...BUNDLE, current_week: null } },
        TABLE,
        calendar(1, 2, 30),
      ),
    ).toBeNull();
    expect(memberClubs({ ok: false, reason: "network" }, TABLE, calendar(1, 2, 30))).toBeNull();
  });
});

describe("the LIVE pill", () => {
  it("opens the member's LIVE page while one of their matches is played", async () => {
    const fetcher = site(calendar(3, 4, 30));
    const { result } = pill(TARGET);
    await waitFor(() => expect(result.current).toBe(TARGET.to));
    expect(asked(fetcher)).toContain(`/api/v1/fpl/entry/${ENTRY}/bundle`);
  });

  it("stays away while only other clubs play", async () => {
    // Clubs 9 and 10 are none of the member's; club 1 and 2's match was hours ago.
    const fetcher = site(calendar(9, 10, 30));
    const { result } = pill(TARGET);
    await waitFor(() => expect(asked(fetcher)).toContain(`/api/v1/fpl/entry/${ENTRY}/bundle`));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current).toBeNull();
  });

  it("reads nothing past the calendar while no match is in its window", async () => {
    const fetcher = site(calendar(3, 4, 400));
    const { result } = pill(TARGET);
    await waitFor(() => expect(asked(fetcher)).toEqual(["/data/fixtures.json"]));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current).toBeNull();
    expect(asked(fetcher)).toEqual(["/data/fixtures.json"]);
  });

  it("reads nothing where there is no phone bar or nobody to open", async () => {
    const fetcher = site(calendar(3, 4, 30));
    expect(pill(TARGET, false).result.current).toBeNull();
    expect(pill(null).result.current).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("counts every match of the week where the member's clubs cannot be read", async () => {
    site(calendar(9, 10, 30), () => marked({ error: "upstream_unavailable" }, 503));
    const { result } = pill(TARGET);
    await waitFor(() => expect(result.current).toBe(TARGET.to));
  });
});
