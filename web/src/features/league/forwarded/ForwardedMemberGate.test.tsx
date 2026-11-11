/**
 * The gate in front of a team read through the forwarder (#983 step 4): the newest capture
 * table the directory names, the team's bundle for its gameweek and the identity rule that
 * binds them. Bound, the member page the address names is drawn under the forwarded league's
 * tree, behind the member step for a league and without one for a team on its own. Not
 * bound, the gate says the plan cannot be computed this week and shows nothing else.
 */

import { createHash } from "node:crypto";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import deviceInstances from "../../../fixtures/device-plan/instances.json";
import {
  bundleHolding,
  fixtureCaptureTable,
  STANDINGS_EXAMPLES,
} from "../../../fixtures/forwarder";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { jsonResponse, stubFetchByUrl, type FetchRoute } from "../../../testSupport/fetchByUrl";
import { AS_A_CAVEAT, AS_A_CHANCE } from "../../../testSupport/honesty";
import type { FplEntryBundle, FplLeagueStandings } from "../forwarder/documents";
import { LeagueMemberPage } from "../pages/LeagueMemberPage";
import { useLeague } from "../useLeague";
import { ForwardedLeagueContext } from "./ForwardedLeagueContext";
import { ForwardedMemberGate } from "./ForwardedMemberGate";
import { forwardedKeys } from "./reads";
import type { ForwardedSources } from "./forwardedTree";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  localStorage.clear();
});

const copy = MESSAGES.tr;
const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const OLDER = "fpl-live-20261009T060000Z-ba9876543210";
const TABLE = fixtureCaptureTable(CAPTURE);
const member = deviceInstances.members[2]!;
const ENTRY = member.entry_id;
const FIFTEEN = [101, 111, 114, 115, 116, 131, 132, 136, 139, 154, 155, 105, 123, 148, 156];
const WORTH = Object.values(member.entry.sell_tenths).reduce((sum, price) => sum + price, 0);
const BUNDLE = bundleHolding(ENTRY, TABLE.gameweek, FIFTEEN, {
  bank: member.entry.bank_tenths,
  value: member.entry.bank_tenths + WORTH,
  captain: 132,
  vice: 139,
});
const PAGE = (() => {
  const page = structuredClone(STANDINGS_EXAMPLES.first_page) as FplLeagueStandings;
  page.results[0] = { ...page.results[0]!, entry: ENTRY };
  return page;
})();
const ROW = PAGE.results[0]!;
/** The table goes on: page 1 says so, and page 2 holds the last members. */
const PAGE_TWO = STANDINGS_EXAMPLES.last_page as FplLeagueStandings;
const LATER = PAGE_TWO.results[1]!;

function text(value: unknown): string {
  return JSON.stringify(value);
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function envelope(payload: unknown, contract = "provisional_league_ui_v1") {
  return {
    contract_version: contract,
    generated_at_utc: "2026-10-16T08:00:00Z",
    source_kind: "live",
    payload,
  };
}

const TABLE_BYTES = text(envelope(TABLE));
const OLDER_BYTES = text(envelope({ ...TABLE, gameweek: 6, source_snapshot_id: OLDER }));

function line(leagueId: number, gameweek: number, capture: string, bytes: string) {
  return {
    league_id: leagueId,
    league_name: `League ${leagueId}`,
    season: "2026-27",
    gameweek,
    path: `leagues/${leagueId}`,
    device_plan: `device/${capture}/device-plan.json`,
    device_plan_sha256: sha256(bytes),
  };
}

function marked(value: unknown, status = 200): Response {
  return new Response(text(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-squadopt-fpl": "1" },
  });
}

const OPEN_WEEK = envelope(
  {
    season: TABLE.season,
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-16T06:00:00Z",
    current_gameweek: TABLE.gameweek - 1,
    unscheduled_count: 0,
    gameweeks: [{ gameweek: TABLE.gameweek, deadline_utc: "2999-01-01T00:00:00Z", fixtures: [] }],
  },
  "fixtures_v1",
);

/** The directory with the newest line naming this capture's table, the calendar, and the forwarder. */
function site({
  bundle = () => marked(BUNDLE),
  lines = [line(352490, 6, OLDER, OLDER_BYTES), line(755941, 7, CAPTURE, TABLE_BYTES)],
  extra = [],
}: { bundle?: () => Response; lines?: unknown[]; extra?: FetchRoute[] } = {}) {
  return stubFetchByUrl([
    ...extra,
    ["/data/leagues.json", () => jsonResponse(envelope({ leagues: lines }, "league_directory_v1"))],
    [
      /\/data\/device\/[^/]+\/device-plan\.json\?v=/,
      (url) => new Response(url.includes(CAPTURE) ? TABLE_BYTES : OLDER_BYTES),
    ],
    ["/data/fixtures.json", () => jsonResponse(OPEN_WEEK)],
    [`/api/v1/fpl/entry/${ENTRY}/bundle?gw=${TABLE.gameweek}`, bundle],
    [/\/api\/v1\/fpl\/standings\/314\?page=1$/, () => marked(PAGE)],
    [/\/api\/v1\/fpl\/standings\/314\?page=2$/, () => marked(PAGE_TWO)],
  ]);
}

/** The tree's own forwarder reads: the page and the member's bundle, no other team. */
const SOURCES: ForwardedSources = {
  standings: async () => ({ ok: true, document: PAGE, copy: "hit" }),
  entryBundle: async (entry: number) =>
    entry === ENTRY
      ? { ok: true, document: BUNDLE as FplEntryBundle, copy: "hit" }
      : { ok: false, reason: "entry_not_found" },
  entrySeason: async () => ({ ok: false, reason: "entry_not_found" }),
  events: async () => ({ ok: false, reason: "not_found" }),
  h2hMatches: async () => ({ ok: false, reason: "not_found" }),
};

/** What the page under the gate is handed: the league in context and its tree. */
function Probe() {
  const { league, tree, forwarded } = useLeague();
  return (
    <p data-testid="probe">
      {`league ${league.leagueId} forwarded ${String(forwarded === true)} capture ${tree.league.devicePlan?.path.split("/")[1]}`}
    </p>
  );
}

function open(
  address: string,
  child: ReactNode = <Probe />,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route
              path="/entry/:entryId"
              element={
                <ForwardedMemberGate standalone sources={SOURCES}>
                  {child}
                </ForwardedMemberGate>
              }
            />
            <Route
              path="/league/:leagueId/members/:entryId/:tool?"
              element={
                <ForwardedLeagueContext.Provider
                  value={{ leagueId: 314, leagueName: "Synthetic League", scoring: "classic" }}
                >
                  <ForwardedMemberGate sources={SOURCES}>{child}</ForwardedMemberGate>
                </ForwardedLeagueContext.Provider>
              }
            />
          </Routes>
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe("a member of a forwarded league", () => {
  it("is asked who they are from the standings, then drawn under the league's forwarded tree", async () => {
    site();
    open(`/league/314/members/${ENTRY}`);
    const option = await screen.findByRole("button", { name: new RegExp(ROW.entry_name) });
    expect(screen.queryByTestId("probe")).toBeNull();
    await userEvent.click(option);
    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent(
        `league 314 forwarded true capture ${CAPTURE}`,
      ),
    );
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toMatchObject({
      leagueId: 314,
      entryId: ENTRY,
      teamName: ROW.entry_name,
    });
  });

  it("reads the table's next page when the team number given is not on page 1", async () => {
    const fetcher = site();
    open(`/league/314/members/${ENTRY}`);
    await screen.findByRole("button", { name: new RegExp(ROW.entry_name) });
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("page=2"))).toBe(false);
    await userEvent.type(screen.getByRole("textbox"), `${LATER.entry}{Enter}`);
    const option = await screen.findByRole("button", { name: new RegExp(LATER.entry_name) });
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("page=2"))).toHaveLength(1);
    await userEvent.click(option);
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toMatchObject({
      leagueId: 314,
      entryId: LATER.entry,
    });
  });

  it("keeps a claim made on a later page, reading the table until the member is found", async () => {
    site();
    sessionStorage.setItem(
      "squadopt.member",
      JSON.stringify({
        leagueId: 314,
        leagueName: "Synthetic League",
        entryId: LATER.entry,
        managerName: LATER.player_name,
        teamName: LATER.entry_name,
      }),
    );
    open(`/league/314/members/${ENTRY}`);
    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("league 314 forwarded true"),
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(JSON.parse(sessionStorage.getItem("squadopt.member")!)).toMatchObject({
      entryId: LATER.entry,
    });
  });

  it("opens straight away as a team on its own, under league 0", async () => {
    site();
    open(`/entry/${ENTRY}`);
    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent(
        `league 0 forwarded true capture ${CAPTURE}`,
      ),
    );
    expect(screen.queryByRole("button", { name: new RegExp(ROW.entry_name) })).toBeNull();
  });

  it("keeps the page drawn when a later read of the bundle fails", async () => {
    let answer = true;
    site({
      bundle: () => (answer ? marked(BUNDLE) : marked({ error: "upstream_unavailable" }, 503)),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    open(`/entry/${ENTRY}`, <Probe />, client);
    await waitFor(() => expect(screen.getByTestId("probe")).toBeInTheDocument());
    answer = false;
    await act(async () => {
      await client.refetchQueries({ queryKey: forwardedKeys.bundle(ENTRY, TABLE.gameweek) });
    });
    expect(client.getQueryState(forwardedKeys.bundle(ENTRY, TABLE.gameweek))?.status).toBe("error");
    expect(screen.getByTestId("probe")).toBeInTheDocument();
    expect(screen.queryByText(copy.forwarded.teamUnavailable)).toBeNull();
  });

  it("says a team cannot be read when no bundle is held, and reads it again on request", async () => {
    let answer = false;
    site({
      bundle: () => (answer ? marked(BUNDLE) : marked({ error: "upstream_unavailable" }, 503)),
    });
    open(`/entry/${ENTRY}`);
    expect(await screen.findByText(copy.forwarded.teamUnavailable)).toBeInTheDocument();
    answer = true;
    await userEvent.click(screen.getByRole("button", { name: copy.forwarded.retry }));
    await waitFor(() => expect(screen.getByTestId("probe")).toBeInTheDocument());
  });

  it("draws the member page itself with the device's controls and no caveat", async () => {
    site();
    open(`/entry/${ENTRY}`, <LeagueMemberPage />);
    await screen.findByRole("heading", { level: 1, name: BUNDLE.entry.name });
    await waitFor(() => expect(document.querySelector("[data-device-compute]")).not.toBeNull());
    expect(screen.queryByText(copy.suggestionHistory.title)).toBeNull();
    expect(document.body.textContent).not.toMatch(AS_A_CHANCE);
    expect(document.body.textContent).not.toMatch(AS_A_CAVEAT);
  });
});

describe("a team the gate cannot bind", () => {
  it("says the plan cannot be computed when the bundle holds another week's picks", async () => {
    site({ bundle: () => marked({ ...BUNDLE, picks: [BUNDLE.picks[0]] }) });
    open(`/entry/${ENTRY}`);
    expect(await screen.findByText(copy.forwarded.planNotComputable)).toBeInTheDocument();
    expect(screen.queryByTestId("probe")).toBeNull();
  });

  it("says the plan cannot be computed when the directory names no table", async () => {
    site({ lines: [{ ...line(352490, 6, OLDER, OLDER_BYTES), device_plan: undefined }] });
    open(`/entry/${ENTRY}`);
    expect(await screen.findByText(copy.forwarded.planNotComputable)).toBeInTheDocument();
  });

  it("names an id FPL has no team for", async () => {
    site({ bundle: () => marked({ error: "entry_not_found", entry: ENTRY }, 404) });
    open(`/entry/${ENTRY}`);
    expect(await screen.findByText(copy.forwarded.teamNotFound(ENTRY))).toBeInTheDocument();
  });

  it("refuses an address that is not a team number", async () => {
    site();
    open("/entry/abc");
    expect(await screen.findByText(copy.leagueMembers.invalidEntry)).toBeInTheDocument();
  });
});

describe("with a compute service configured", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("asks the public capabilities route for the team, under league 0", async () => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "https://api.example");
    const capabilities = {
      contract_version: "league_capabilities_v1",
      league_id: 0,
      capture_snapshot_id: CAPTURE,
      season: TABLE.season,
      gameweek: TABLE.gameweek,
      strategies: { "saf-puan": { windows: [1, 3, 5], requires_rival: false } },
      top100: { available: false, weights: [0] },
      managers_word: { available: false },
      preferences: { available: true },
      chips: {
        strategy: { version: "dated_joint_opportunity_v3", windows: [1, 3, 5] },
        held_by_entry: {},
      },
    };
    const fetcher = site({
      extra: [
        [
          `/api/v1/public/leagues/0/entries/${ENTRY}/capabilities`,
          () => jsonResponse(capabilities),
        ],
      ],
    });
    open(`/entry/${ENTRY}`, <LeagueMemberPage />);
    await screen.findByRole("heading", { level: 1, name: BUNDLE.entry.name });
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([url]) =>
          String(url).endsWith(`/api/v1/public/leagues/0/entries/${ENTRY}/capabilities`),
        ),
      ).toBe(true),
    );
    expect(
      fetcher.mock.calls.some(([url]) => String(url).includes("/api/v1/leagues/0/capabilities")),
    ).toBe(false);
  });
});
