/**
 * #983 step 4, the league gate for a league the site does not publish: page 1 of its
 * classic standings from the FPL forwarder, and the table read page by page from there. A
 * listed league opens from the published tree and asks the forwarder nothing; a head-to-head
 * league and an unknown id are named; a forwarder that cannot answer says the league cannot
 * be opened now and offers the listed leagues.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STANDINGS_EXAMPLES } from "../../../fixtures/forwarder";
import { mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { memberAddress } from "../../../lib/leagueAddresses";
import { jsonResponse, stubFetchByUrl } from "../../../testSupport/fetchByUrl";
import { claimIn, forgetIdentity } from "../../../testSupport/league";
import { MAX_STANDINGS_PAGE, type FplLeagueStandings } from "../forwarder/documents";
import { readChosenLeague } from "../identity/useChosenLeague";
import { LeagueGate } from "../pages/LeagueGate";
import { ForwardedLeaguePage } from "./ForwardedLeaguePage";
import { useForwardedLeague } from "./ForwardedLeagueContext";

const published = { ...mockLeagueMembersEnvelope, source_kind: "live" };
const LISTED = published.payload.league_id;
const FORWARDED = STANDINGS_EXAMPLES.first_page.league.id;
const FIRST = STANDINGS_EXAMPLES.first_page as FplLeagueStandings;
const LAST = STANDINGS_EXAMPLES.last_page as FplLeagueStandings;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  forgetIdentity();
});

/** An answer of the forwarder: JSON with its mark. */
function marked(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "x-squadopt-fpl": "1" },
  });
}

/** A site with one published league, in a directory, and a forwarder answering `standings`. */
function site(standings: (page: number) => Response) {
  return stubFetchByUrl([
    [
      "/data/leagues.json",
      () =>
        jsonResponse({
          contract_version: "league_directory_v1",
          generated_at_utc: published.generated_at_utc,
          source_kind: "live",
          payload: {
            leagues: [
              {
                league_id: LISTED,
                league_name: published.payload.league_name,
                season: published.payload.season,
                gameweek: published.payload.gameweek,
                path: "league",
              },
            ],
          },
        }),
    ],
    ["/data/league/members.json", () => jsonResponse(published)],
    [/\/api\/v1\/fpl\/standings\/\d+\?page=\d+$/, (url) => standings(Number(url.split("=")[1]))],
  ]);
}

const forwarderReads = (fetcher: ReturnType<typeof site>) =>
  fetcher.mock.calls.map(([url]) => url).filter((url) => url.startsWith("/api/v1/fpl/"));

function LocationProbe() {
  const location = useLocation();
  return (
    <span data-testid="location">
      {location.pathname}
      {location.search}
    </span>
  );
}

function ForwardedMember() {
  return <h1>Forwarded member {useForwardedLeague()?.leagueId}</h1>;
}

function open(language: Language, address: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LanguageProvider initialLanguage={language}>
        <MemoryRouter initialEntries={[address]}>
          <Routes>
            <Route
              path="/league/:leagueId"
              element={
                <LeagueGate forwarded={<ForwardedLeaguePage />}>
                  <h1>Published league</h1>
                </LeagueGate>
              }
            />
            <Route
              path="/league/:leagueId/members/:entryId"
              element={
                <LeagueGate forwarded={<ForwardedMember />}>
                  <h1>Published member</h1>
                </LeagueGate>
              }
            />
            <Route
              path="/league/:leagueId/members/:entryId/history"
              element={
                <LeagueGate>
                  <h1>Published history</h1>
                </LeagueGate>
              }
            />
            <Route path="/league/:leagueId/members" element={<h1>Members list</h1>} />
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("the league gate with the forwarder in %s", (language) => {
  const copy = MESSAGES[language].leagueEntry;
  const words = MESSAGES[language].forwarded;
  const members = MESSAGES[language].leagueMembers;

  it("opens a listed league from the published tree, asking the forwarder nothing", async () => {
    const fetcher = site(() => new Response("<!doctype html>", { status: 200 }));
    claimIn();
    open(language, `/league/${LISTED}`);
    expect(await screen.findByRole("heading", { name: "Published league" })).toBeInTheDocument();
    expect(forwarderReads(fetcher)).toEqual([]);
    expect(readChosenLeague()).toBe(LISTED);
  });

  it("opens an unlisted classic league from its standings, never choosing it", async () => {
    const fetcher = site(() => marked(FIRST));
    open(language, `/league/${FORWARDED}`);
    expect(await screen.findByRole("heading", { name: FIRST.league.name! })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: members.caption(FIRST.league.name!) });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(FIRST.results.length);
    const first = FIRST.results[0]!;
    expect(rows[0]).toHaveTextContent(String(first.rank));
    expect(rows[0]).toHaveTextContent(first.player_name);
    expect(within(rows[0]!).getByRole("link", { name: first.entry_name })).toHaveAttribute(
      "href",
      memberAddress(FORWARDED, first.entry),
    );
    expect(forwarderReads(fetcher)).toEqual([`/api/v1/fpl/standings/${FORWARDED}?page=1`]);
    expect(readChosenLeague()).toBeNull();
    // Nothing published is read for it: no members, no scoreboard, no advice.
    expect(fetcher.mock.calls.map(([url]) => url)).not.toContain(
      expect.stringContaining(`leagues/${FORWARDED}`),
    );
  });

  it("opens a member of the forwarded league under it, and no history", async () => {
    site(() => marked(FIRST));
    open(language, memberAddress(FORWARDED, 5001));
    expect(
      await screen.findByRole("heading", { name: `Forwarded member ${FORWARDED}` }),
    ).toBeInTheDocument();
    cleanup();
    open(language, `${memberAddress(FORWARDED, 5001)}/history`);
    expect(await screen.findByText(MESSAGES[language].shell.notFound)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Published history" })).toBeNull();
  });

  it("names a head-to-head league", async () => {
    site(() => marked({ error: "head_to_head_league", league: FORWARDED }, 404));
    open(language, `/league/${FORWARDED}`);
    expect(await screen.findByText(copy.headToHead(FORWARDED))).toBeInTheDocument();
    expect(screen.getByLabelText(copy.label)).toHaveValue(String(FORWARDED));
    expect(screen.queryByRole("navigation", { name: copy.listedLeagues })).toBeNull();
  });

  it("names an id FPL has no league for", async () => {
    site(() => marked({ error: "league_not_found" }, 404));
    open(language, `/league/${FORWARDED}`);
    expect(await screen.findByText(copy.unknownLeague(FORWARDED))).toBeInTheDocument();
  });

  it.each([
    ["absent, the site's shell answering", () => new Response("<!doctype html>", { status: 200 })],
    ["unable to reach FPL", () => marked({ error: "upstream_unavailable" }, 503)],
    ["unreachable", () => Promise.reject(new TypeError("network")) as unknown as Response],
  ])(
    "says the league cannot be opened now with the forwarder %s, and offers the listed leagues",
    async (_name, answer) => {
      let down = true;
      const fetcher = site(() => (down ? answer() : marked(FIRST)));
      open(language, `/league/${FORWARDED}`);
      expect(await screen.findByText(copy.cannotOpen(FORWARDED))).toBeInTheDocument();
      const listed = screen.getByRole("navigation", { name: copy.listedLeagues });
      expect(
        within(listed).getByRole("link", { name: published.payload.league_name }),
      ).toHaveAttribute("href", `/league/${LISTED}`);
      // Read again on request, once the forwarder answers.
      down = false;
      await userEvent.setup().click(screen.getByRole("button", { name: copy.retry }));
      expect(await screen.findByRole("heading", { name: FIRST.league.name! })).toBeInTheDocument();
      expect(forwarderReads(fetcher)).toHaveLength(2);
    },
  );

  it("reads the next page on request, and stops after the last", async () => {
    const fetcher = site((page) => marked(page === 1 ? FIRST : LAST));
    open(language, `/league/${FORWARDED}`);
    const more = await screen.findByRole("button", { name: words.nextPage });
    await userEvent.setup().click(more);
    expect(await screen.findByRole("link", { name: LAST.results[0]!.entry_name })).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(1 + LAST.results.length);
    expect(screen.getByRole("button", { name: words.nextPage })).toBeDisabled();
    expect(screen.getByTestId("location")).toHaveTextContent(`?page=2`);
    await userEvent.setup().click(screen.getByRole("button", { name: words.previousPage }));
    expect(await screen.findByRole("link", { name: FIRST.results[0]!.entry_name })).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(1 + FIRST.results.length);
    expect(forwarderReads(fetcher)).toEqual([
      `/api/v1/fpl/standings/${FORWARDED}?page=1`,
      `/api/v1/fpl/standings/${FORWARDED}?page=2`,
    ]);
  });

  it("says when the next page could not be read, and reads it again", async () => {
    let fail = true;
    site((page) =>
      page === 1
        ? marked(FIRST)
        : fail
          ? marked({ error: "upstream_unavailable" }, 503)
          : marked(LAST),
    );
    open(language, `/league/${FORWARDED}`);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: words.nextPage }));
    expect(await screen.findByText(words.moreFailed)).toBeInTheDocument();
    // A failed page never presents the previous page's rows as its own.
    expect(screen.queryByRole("link", { name: FIRST.results[0]!.entry_name })).toBeNull();
    expect(screen.getByRole("button", { name: words.previousPage })).toBeEnabled();
    fail = false;
    await user.click(screen.getByRole("button", { name: words.retry }));
    expect(await screen.findByRole("link", { name: LAST.results[0]!.entry_name })).toBeVisible();
    expect(screen.queryByText(words.moreFailed)).toBeNull();
  });
});

describe("large forwarded leagues", () => {
  function page(number: number): FplLeagueStandings {
    return {
      ...FIRST,
      page: number,
      has_next: number < 406,
      results: FIRST.results.map((row) => ({
        ...row,
        entry: row.entry + number * 100,
        entry_name: `${row.entry_name} p${number}`,
        rank: (number - 1) * 50 + row.rank,
      })),
    };
  }

  it("jumps beyond the old cap without reading intervening pages or accumulating rows", async () => {
    const fetcher = site((number) => marked(page(number)));
    open("en", `/league/${FORWARDED}?page=406`);
    expect(
      await screen.findByRole("link", { name: page(406).results[0]!.entry_name }),
    ).toBeVisible();
    expect(forwarderReads(fetcher)).toEqual([
      `/api/v1/fpl/standings/${FORWARDED}?page=1`,
      `/api/v1/fpl/standings/${FORWARDED}?page=406`,
    ]);
    expect(screen.getAllByRole("row")).toHaveLength(1 + FIRST.results.length);
    expect(screen.getByRole("button", { name: MESSAGES.en.forwarded.nextPage })).toBeDisabled();
    const user = userEvent.setup();
    const field = screen.getByRole("textbox", { name: MESSAGES.en.forwarded.page });
    await user.clear(field);
    await user.type(field, "21");
    await user.click(screen.getByRole("button", { name: MESSAGES.en.forwarded.go }));
    expect(
      await screen.findByRole("link", { name: page(21).results[0]!.entry_name }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: page(406).results[0]!.entry_name })).toBeNull();
    expect(forwarderReads(fetcher)).toHaveLength(3);
    expect(screen.getByTestId("location")).toHaveTextContent("?page=21");
  });

  it("does not request an out-of-range page submitted by the visitor", async () => {
    const fetcher = site((number) => marked(page(number)));
    open("en", `/league/${FORWARDED}`);
    const field = await screen.findByRole("textbox", { name: MESSAGES.en.forwarded.page });
    const user = userEvent.setup();
    await user.clear(field);
    await user.type(field, String(MAX_STANDINGS_PAGE + 1));
    await user.click(screen.getByRole("button", { name: MESSAGES.en.forwarded.go }));
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(forwarderReads(fetcher)).toHaveLength(1);
  });

  it("normalizes an invalid URL page and retains the forwarder's upper bound", async () => {
    const fetcher = site((number) => marked({ ...page(number), has_next: true }));
    open("en", `/league/${FORWARDED}?page=${MAX_STANDINGS_PAGE}`);
    expect(
      await screen.findByRole("link", { name: page(MAX_STANDINGS_PAGE).results[0]!.entry_name }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: MESSAGES.en.forwarded.nextPage })).toBeDisabled();
    expect(forwarderReads(fetcher)).toHaveLength(2);
    cleanup();
    open("en", `/league/${FORWARDED}?page=-1`);
    expect(await screen.findByRole("link", { name: page(1).results[0]!.entry_name })).toBeVisible();
    expect(screen.getByRole("textbox", { name: MESSAGES.en.forwarded.page })).toHaveValue("1");
  });
});
