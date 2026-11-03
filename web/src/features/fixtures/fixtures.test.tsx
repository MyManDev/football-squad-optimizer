import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Link, MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PageShell } from "../../design/components/PageShell";
import { AS_A_CHANCE } from "../../testSupport/honesty";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../i18n/messages";
import { CLUB_COLOURS } from "../../lib/clubs";
import { loadFixtures } from "./data";
import { FIXTURES_COPY } from "./fixturesCopy";
import { FixturesPage } from "./FixturesPage";
import { FixtureMatrix } from "./FixtureMatrix";
import { fixtureDay, fixtureTime } from "./kickoff";
import { TeamFixtures } from "./TeamFixtures";
import type { Fixture, FixturesPayload } from "./types";
import { clubMatrix, clubWeeksAhead, fixtureClubs, generalWeeks, weeksAhead } from "./weeks";

/** The shipped calendar: its first gameweek names all twenty clubs of the season. */
const shipped = JSON.parse(
  readFileSync(join(__dirname, "../../../public/data/fixtures.json"), "utf-8"),
) as { payload: FixturesPayload };

const SEASON_CODES = [
  "ARS",
  "AVL",
  "BHA",
  "BOU",
  "BRE",
  "CHE",
  "COV",
  "CRY",
  "EVE",
  "FUL",
  "HUL",
  "IPS",
  "LEE",
  "LIV",
  "MCI",
  "MUN",
  "NEW",
  "NFO",
  "SUN",
  "TOT",
];

const team = (team_id: number, name: string, short_name: string) => ({ team_id, name, short_name });
const ARS = team(1, "Arsenal", "ARS");
const AVL = team(2, "Aston Villa", "AVL");
const BRE = team(3, "Brentford", "BRE");
const CHE = team(4, "Chelsea", "CHE");

const played = (fixture_id: number, home = ARS, away = AVL, score = [3, 0]): Fixture => ({
  fixture_id,
  kickoff_utc: "2026-08-22T14:00:00Z",
  home,
  away,
  finished: true,
  home_score: score[0]!,
  away_score: score[1]!,
});

const upcoming = (
  fixture_id: number,
  home: typeof ARS,
  away: typeof ARS,
  kickoff_utc: string | null,
): Fixture => ({
  fixture_id,
  kickoff_utc,
  home,
  away,
  finished: false,
  home_score: null,
  away_score: null,
});

function payload(current: number | null = 3): FixturesPayload {
  return {
    season: "2026-27",
    source_snapshot_id: "fpl-live-synthetic",
    captured_at_utc: "2026-09-17T10:33:11Z",
    current_gameweek: current,
    unscheduled_count: 1,
    gameweeks: [
      { gameweek: 1, deadline_utc: "2026-08-21T17:30:00Z", fixtures: [played(1)] },
      {
        gameweek: 2,
        deadline_utc: "2026-08-28T17:30:00Z",
        fixtures: [played(2, BRE, CHE, [0, 0])],
      },
      {
        gameweek: 3,
        deadline_utc: "2026-09-19T10:00:00Z",
        fixtures: [
          played(3, CHE, ARS, [1, 2]),
          upcoming(4, AVL, BRE, "2026-09-20T13:00:00Z"),
          upcoming(5, ARS, BRE, null),
        ],
      },
      {
        gameweek: 4,
        deadline_utc: "2026-09-26T10:00:00Z",
        fixtures: [upcoming(6, BRE, ARS, "2026-09-26T14:00:00Z")],
      },
    ],
  };
}

/** Seven weeks ahead, each with one fixture but the first: more than the matrix shows. */
function longRun(): FixturesPayload {
  const base = payload();
  return {
    ...base,
    gameweeks: [
      ...base.gameweeks,
      ...[5, 6, 7, 8, 9].map((gameweek) => ({
        gameweek,
        deadline_utc: `2026-10-${gameweek + 10}T10:00:00Z`,
        fixtures: [upcoming(gameweek * 10, ARS, CHE, `2026-10-${gameweek + 11}T14:00:00Z`)],
      })),
    ],
  };
}

function serve(body: string, status = 200) {
  const fetchMock = vi.fn(async () => new Response(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const published = (view: FixturesPayload) =>
  JSON.stringify({ contract_version: "fixtures_v1", generated_at_utc: "now", payload: view });

function Address() {
  const { pathname, search } = useLocation();
  return <output data-testid="address">{pathname + search}</output>;
}

function surface(
  node: React.ReactNode,
  language: Language = "en",
  path = "/league/352490/members/1",
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <LanguageProvider initialLanguage={language}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <div data-testid="surface">{node}</div>
          <Address />
        </MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
}

const headings = () => screen.getAllByRole("heading", { level: 2 }).map((node) => node.textContent);

/** Sets the page's clock; the mock of the day is the one `beforeEach` installs. */
const atClock = (iso: string) => vi.spyOn(Date, "now").mockReturnValue(Date.parse(iso));

/** The matrix, once the page has drawn it. */
const findMatrix = () => screen.findByRole("table", { name: FIXTURES_COPY.en.generalView });

/** What the matrix's column heads print, in order. */
const columnsOf = (matrix: HTMLElement) =>
  within(matrix)
    .getAllByRole("columnheader")
    .map((node) => node.textContent);

/** The cells of one club's line of the matrix, found by its code. */
const lineOf = (matrix: HTMLElement, code: string) =>
  within(
    within(matrix)
      .getByRole("rowheader", { name: new RegExp(`^${code}`) })
      .closest("tr")!,
  ).getAllByRole("cell");

/** What each radio of a named group prints, in order. */
const optionsOf = (group: HTMLElement) =>
  within(group)
    .getAllByRole("radio")
    .map((radio) => radio.closest("label")!.textContent);

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-18T10:00:00Z"));
});
afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  vi.unstubAllGlobals();
});

describe("fixtures in the shell", () => {
  it.each(["tr", "en"] as const)(
    "carries no league-wide rail and links the fixture list from the sidebar in %s",
    async (language) => {
      const fetchMock = serve(published(payload()));
      const { container } = render(
        surface(
          <PageShell>
            <p>page</p>
          </PageShell>,
          language,
          "/league/352490",
        ),
      );
      const copy = FIXTURES_COPY[language];
      const shell = MESSAGES[language].shell;

      // The two margin rails and the closed list under the page are gone: the member page
      // carries its own fixtures, and /fixtures carries the matches still to come.
      expect(screen.queryByRole("complementary", { name: copy.pageTitle })).toBeNull();
      expect(
        screen.getAllByRole("complementary").map((node) => node.getAttribute("aria-label")),
      ).toEqual([shell.sidebar]);
      expect(container.querySelector("details")).toBeNull();

      const nav = screen.getByRole("navigation", { name: shell.primary });
      expect(within(nav).getByRole("link", { name: shell.fixtures })).toHaveAttribute(
        "href",
        "/fixtures",
      );
      // The shell reads no document of its own.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 25));
      });
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );
});

describe("the fixtures page", () => {
  it("opens on the general view's matrix, with no played week anywhere", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    await screen.findByRole("heading", { level: 1, name: "Fixtures" });
    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.generalView })).toBeChecked();
    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.teamView })).not.toBeChecked();
    expect(columnsOf(await findMatrix())).toEqual([FIXTURES_COPY.en.clubLegend, "GW3", "GW4"]);
    expect(screen.getByTestId("surface")).toHaveTextContent(FIXTURES_COPY.en.unscheduledCount(1));
    expect(FIXTURES_COPY.en).not.toHaveProperty("pastTitle");
    expect(FIXTURES_COPY.tr).not.toHaveProperty("pastTitle");
  });

  it("says so when no fixture list is published", async () => {
    serve("Not found", 404);
    render(surface(<FixturesPage />, "tr", "/fixtures"));
    expect(
      await screen.findByRole("heading", { level: 1, name: FIXTURES_COPY.tr.notPublished }),
    ).toBeInTheDocument();
  });

  it.each([
    ["the host's HTML shell", "<!doctype html><html><body></body></html>"],
    [
      "another contract",
      JSON.stringify({
        contract_version: "ui_view_v1",
        generated_at_utc: "now",
        payload: payload(),
      }),
    ],
  ])("treats %s as no fixture list, not as an error", async (_label, body) => {
    serve(body);
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(await screen.findByText(FIXTURES_COPY.en.notPublished)).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "says only that nothing is left when the season is over in %s",
    async (language) => {
      atClock("2027-01-01T00:00:00Z");
      serve(published({ ...payload(null), unscheduled_count: 0 }));
      render(surface(<FixturesPage />, language, "/fixtures"));
      const copy = FIXTURES_COPY[language];
      await screen.findByText(copy.noneAhead);
      expect(screen.getByTestId("surface").textContent).toBe(
        `2026-27${copy.pageTitle}${copy.noneAhead}`,
      );
    },
  );

  it("does not say nothing is left while a postponed match waits for its gameweek", async () => {
    atClock("2027-01-01T00:00:00Z");
    serve(published(payload(null)));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const copy = FIXTURES_COPY.en;
    await screen.findByText(copy.unscheduledCount(1));
    expect(screen.getByTestId("surface").textContent).toBe(
      `2026-27${copy.pageTitle}${copy.unscheduledCount(1)}`,
    );
  });

  it("offers no choice for a calendar that names no club", async () => {
    serve(
      published({
        ...payload(),
        unscheduled_count: 0,
        gameweeks: [
          { gameweek: 3, deadline_utc: "2026-09-19T10:00:00Z", fixtures: [] },
          { gameweek: 4, deadline_utc: "2026-09-26T10:00:00Z", fixtures: [] },
        ],
      }),
    );
    render(surface(<FixturesPage />, "en", "/fixtures?view=team"));
    await screen.findByText(FIXTURES_COPY.en.noneAhead);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("carries no wording of chance", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "tr", "/fixtures"));
    await screen.findByRole("table", { name: FIXTURES_COPY.tr.generalView });
    expect(screen.getByTestId("surface").textContent).not.toMatch(AS_A_CHANCE);
  });

  it("opens the matrix on a view it does not know", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=xyz"));
    await screen.findByRole("heading", { level: 1, name: "Fixtures" });
    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.generalView })).toBeChecked();
    expect(columnsOf(await findMatrix())).toEqual([FIXTURES_COPY.en.clubLegend, "GW3", "GW4"]);
  });

  it.each([
    ["en", "3 postponed fixtures have no new gameweek yet."],
    ["tr", "Ertelenen 3 maçın yeni oyun haftası henüz belli değil."],
  ] as const)("counts several postponed fixtures in %s", async (language, sentence) => {
    serve(published({ ...payload(), unscheduled_count: 3 }));
    render(surface(<FixturesPage />, language, "/fixtures"));
    expect(await screen.findByText(sentence)).toBeInTheDocument();
  });

  it("says it is loading, not that nothing is published, while the document is on its way", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(surface(<FixturesPage />, "tr", "/fixtures"));
    expect(screen.getByText(MESSAGES.tr.common.loading)).toBeInTheDocument();
    expect(screen.queryByText(FIXTURES_COPY.tr.notPublished)).not.toBeInTheDocument();
  });

  it("moves the radios when a link changes the address", async () => {
    serve(published(longRun()));
    render(
      surface(
        <>
          <Link to="/fixtures">out</Link>
          <FixturesPage />
        </>,
        "en",
        "/fixtures",
      ),
    );
    fireEvent.click(await screen.findByRole("radio", { name: FIXTURES_COPY.en.teamView }));
    fireEvent.click(screen.getByRole("link", { name: "out" }));
    expect(screen.getByTestId("address")).toHaveTextContent(/^\/fixtures$/);
    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.generalView })).toBeChecked();
    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.teamView })).not.toBeChecked();
  });

  it("rolls on by itself in a tab left open", async () => {
    const clock = atClock("2026-09-18T10:00:00Z");
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      serve(published(longRun()));
      render(surface(<FixturesPage />, "en", "/fixtures"));
      const matrix = await findMatrix();
      expect(columnsOf(matrix).slice(1)).toEqual(["GW3", "GW4", "GW5", "GW6", "GW7"]);
      clock.mockReturnValue(Date.parse("2026-09-28T10:00:00Z"));
      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      expect(columnsOf(matrix).slice(1)).toEqual(["GW5", "GW6", "GW7", "GW8", "GW9"]);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the matrix's window", () => {
  it("has a line for each club and a column for each of the next five gameweeks", async () => {
    serve(published(longRun()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const matrix = await findMatrix();
    expect(columnsOf(matrix)).toEqual([
      FIXTURES_COPY.en.clubLegend,
      "GW3",
      "GW4",
      "GW5",
      "GW6",
      "GW7",
    ]);
    expect(
      within(matrix)
        .getAllByRole("rowheader")
        .map((node) => node.getAttribute("title")),
    ).toEqual(["Arsenal", "Aston Villa", "Brentford", "Chelsea"]);
  });

  it("rolls on by itself as the weeks pass, always five while five are left", async () => {
    // Gameweek 3 is behind by the 22nd and gameweek 4 by the 27th.
    atClock("2026-09-27T12:00:00Z");
    serve(published(longRun()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(columnsOf(await findMatrix())).toEqual([
      FIXTURES_COPY.en.clubLegend,
      "GW5",
      "GW6",
      "GW7",
      "GW8",
      "GW9",
    ]);
  });

  it("offers no choice of weeks, by any address", async () => {
    serve(published(longRun()));
    render(surface(<FixturesPage />, "en", "/fixtures?week=5"));
    const matrix = await findMatrix();
    expect(columnsOf(matrix)).toEqual([
      FIXTURES_COPY.en.clubLegend,
      "GW3",
      "GW4",
      "GW5",
      "GW6",
      "GW7",
    ]);
    expect(screen.getAllByRole("radio").map((radio) => radio.getAttribute("name"))).toEqual([
      "fixture-view",
      "fixture-view",
    ]);
    expect(screen.queryByRole("heading", { level: 2 })).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("narrows to the weeks left near the season's end, down to the last one", async () => {
    atClock("2026-09-22T12:00:00Z");
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(columnsOf(await findMatrix())).toEqual([FIXTURES_COPY.en.clubLegend, "GW4"]);
  });

  it("leaves a week the calendar does not list missing, and does not reach past the five", async () => {
    const view = longRun();
    view.gameweeks = view.gameweeks.filter((week) => week.gameweek !== 5);
    serve(published(view));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(columnsOf(await findMatrix())).toEqual([
      FIXTURES_COPY.en.clubLegend,
      "GW3",
      "GW4",
      "GW6",
      "GW7",
    ]);
  });

  it("keeps a week whose deadline has passed while its matches are still to come", async () => {
    atClock("2026-09-19T12:00:00Z");
    // The capture is what names gameweek 4 as current: its deadline is the first still open.
    serve(published({ ...payload(4), captured_at_utc: "2026-09-19T11:00:00Z" }));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(columnsOf(await findMatrix())).toEqual([FIXTURES_COPY.en.clubLegend, "GW3", "GW4"]);
  });

  it("reads on past the last deadline while a match of the season is still to come", async () => {
    atClock("2026-09-26T11:00:00Z");
    serve(published({ ...payload(null), captured_at_utc: "2026-09-26T10:30:00Z" }));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(columnsOf(await findMatrix())).toEqual([FIXTURES_COPY.en.clubLegend, "GW4"]);
  });
});

describe("the matrix's cells", () => {
  it("gives each club's week its opponent and its venue, from that club's side", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const matrix = await findMatrix();
    const [, week4] = lineOf(matrix, "ARS");
    const match = week4!.querySelector("[data-venue]")!;
    expect(match.textContent).toBe(`BREA${FIXTURES_COPY.en.away}`);
    expect(match).toHaveAttribute("data-venue", "away");
    expect(match).toHaveAttribute("title", "Brentford");
    const [opposite] = lineOf(matrix, "AVL");
    expect(opposite!.querySelector("[data-venue]")).toHaveAttribute("data-venue", "home");
    expect(opposite).toHaveTextContent(`BREH${FIXTURES_COPY.en.atHome}`);
    // A letter to see and the word to hear.
    expect(match.querySelector('.venue [aria-hidden="true"]')).toHaveTextContent(
      MESSAGES.en.leagueMembers.fixtureAway,
    );
    expect(match.querySelector(".venue .visually-hidden")).toHaveTextContent(FIXTURES_COPY.en.away);
  });

  it("says so for a week a club does not play", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const [, week4] = lineOf(await findMatrix(), "AVL");
    expect(week4).toHaveTextContent(MESSAGES.en.leagueMembers.fixtureNone);
    expect(week4!.querySelector("[data-venue]")).toBeNull();
  });

  it("holds both matches of a double week, and marks the one already behind the club", async () => {
    const errors = vi.spyOn(console, "error");
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    // Arsenal has played at Chelsea this week, and still has Brentford with no date.
    const [week3] = lineOf(await findMatrix(), "ARS");
    const [played, toCome] = [...week3!.querySelectorAll("[data-venue]")];
    expect(played!.textContent).toMatch(/^CHE/);
    expect(played).toHaveAttribute("data-behind");
    expect(toCome!.textContent).toMatch(/^BRE/);
    expect(toCome).not.toHaveAttribute("data-behind");
    // A word to hear, for what the quieter tone says to the eye.
    expect(played!.querySelector(".venue .visually-hidden")).toHaveTextContent(
      FIXTURES_COPY.en.kickedOff,
    );
    expect(toCome).not.toHaveTextContent(FIXTURES_COPY.en.kickedOff);
    expect(errors).not.toHaveBeenCalled();
  });

  it("keeps a match past its kickoff in its cell, though the capture has no result yet", async () => {
    atClock("2026-09-20T15:00:00Z");
    // A later match keeps gameweek 3 on the page after Aston Villa's has kicked off.
    const view = payload();
    view.gameweeks[2]!.fixtures.push(upcoming(9, CHE, BRE, "2026-09-21T13:00:00Z"));
    serve(published(view));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const [week3] = lineOf(await findMatrix(), "AVL");
    expect(week3!.querySelector("[data-venue]")).toHaveAttribute("data-behind");
    expect(week3).not.toHaveTextContent(MESSAGES.en.leagueMembers.fixtureNone);
  });

  it("prints no score and no kickoff: those are not what a line is read for", async () => {
    serve(published(payload()));
    const { container } = render(surface(<FixturesPage />, "en", "/fixtures"));
    await findMatrix();
    expect(container.querySelector("time")).toBeNull();
    expect(container.textContent).not.toMatch(/\d - \d/);
  });

  it("names a club on its line by code and by name, for the two widths that print one", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const header = within(await findMatrix()).getByRole("rowheader", { name: /^BRE/ });
    expect(header.querySelector(".clubCode")).toHaveTextContent("BRE");
    expect(header.querySelector(".clubName")).toHaveTextContent("Brentford");
    expect(header).toHaveAttribute("title", "Brentford");
  });
});

describe("the team view", () => {
  const cellsOf = (name: string) =>
    within(screen.getByRole("heading", { level: 2, name }).closest("section")!).getAllByRole(
      "listitem",
    );

  it("opens on the first club, with no matrix", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    fireEvent.click(await screen.findByRole("radio", { name: FIXTURES_COPY.en.teamView }));

    expect(screen.getByRole("radio", { name: FIXTURES_COPY.en.teamView })).toBeChecked();
    expect(screen.getByTestId("address")).toHaveTextContent("/fixtures?view=team");
    expect(optionsOf(screen.getByRole("group", { name: FIXTURES_COPY.en.clubLegend }))).toEqual([
      "ARS Arsenal",
      "AVL Aston Villa",
      "BRE Brentford",
      "CHE Chelsea",
    ]);
    expect(screen.getByRole("radio", { name: "ARS Arsenal" })).toBeChecked();
    expect(headings()).toEqual(["Arsenal"]);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("goes back to the matrix from the view's own choice", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team"));
    fireEvent.click(await screen.findByRole("radio", { name: FIXTURES_COPY.en.generalView }));
    expect(await findMatrix()).toBeInTheDocument();
    expect(screen.getByTestId("address")).toHaveTextContent(/^\/fixtures$/);
  });

  it("says each match's week, venue, opponent, date and time, and nothing else", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=AVL"));
    await screen.findByRole("heading", { level: 2, name: "Aston Villa" });
    const [match] = cellsOf("Aston Villa");
    const kickoff = "2026-09-20T13:00:00Z";
    expect(match!.textContent).toBe(
      `GW3${MESSAGES.en.leagueMembers.fixtureHome}${FIXTURES_COPY.en.atHome}BRE Brentford` +
        `${fixtureDay(kickoff, "en-GB")}${fixtureTime(kickoff, "en-GB")}`,
    );
    const time = match!.querySelector("time")!;
    expect(time).toHaveTextContent(fixtureTime(kickoff, "en-GB"));
    expect(time).toHaveAttribute("datetime", kickoff);
    const opponent = match!.querySelector(".opponent")!;
    expect(opponent).toHaveAttribute("title", "Brentford");
    const swatch = opponent.querySelector<HTMLElement>("[aria-hidden='true']")!;
    expect(swatch.style.getPropertyValue("--club-primary")).toBe(CLUB_COLOURS.BRE!.primary);
    expect(swatch.style.getPropertyValue("--club-secondary")).toBe(CLUB_COLOURS.BRE!.secondary);
    // A letter to see and the word to hear.
    expect(match).toHaveAttribute("data-venue", "home");
    expect(match!.querySelector('.venue [aria-hidden="true"]')).toHaveTextContent(
      MESSAGES.en.leagueMembers.fixtureHome,
    );
  });

  it.each(["tr", "en"] as const)("marks an away match in %s", async (language) => {
    serve(published(payload()));
    render(surface(<FixturesPage />, language, "/fixtures?view=team&team=BRE"));
    await screen.findByRole("heading", { level: 2, name: "Brentford" });
    const [away] = cellsOf("Brentford");
    expect(away).toHaveAttribute("data-venue", "away");
    expect(away!.querySelector('.venue [aria-hidden="true"]')).toHaveTextContent(
      MESSAGES[language].leagueMembers.fixtureAway,
    );
    expect(away).toHaveTextContent(FIXTURES_COPY[language].away);
  });

  it("gives a fixture with no date the copy's word and no time", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=ARS"));
    await screen.findByRole("heading", { level: 2, name: "Arsenal" });
    const [undated, dated] = cellsOf("Arsenal");
    expect(undated).toHaveTextContent(new RegExp(`^GW3.*${FIXTURES_COPY.en.unscheduled}$`));
    expect(undated!.querySelector("time")).toBeNull();
    expect(dated).toHaveTextContent(/^GW4/);
    expect(dated!.querySelector("time")).not.toBeNull();
  });

  it("leaves out a match already played, and says so for a week the club does not play", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=CHE"));
    await screen.findByRole("heading", { level: 2, name: "Chelsea" });
    // Chelsea played its one match of gameweek 3, and gameweek 4 has none for it.
    const cells = cellsOf("Chelsea");
    expect(cells).toHaveLength(1);
    expect(cells[0]!.textContent).toBe(`GW4${MESSAGES.en.leagueMembers.fixtureNone}`);
    expect(cells[0]).toHaveAttribute("data-venue", "none");
  });

  it("leaves out a match past its kickoff since the capture, though the week is still on", async () => {
    atClock("2026-09-20T15:00:00Z");
    // A later match keeps gameweek 3 on the page after Aston Villa's has kicked off.
    const view = payload();
    view.gameweeks[2]!.fixtures.push(upcoming(9, CHE, BRE, "2026-09-21T13:00:00Z"));
    serve(published(view));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=AVL"));
    await screen.findByRole("heading", { level: 2, name: "Aston Villa" });
    expect(cellsOf("Aston Villa").map((cell) => cell.textContent)).toEqual([
      `GW4${MESSAGES.en.leagueMembers.fixtureNone}`,
    ]);
  });

  it("prints a date in the visitor's language", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "tr", "/fixtures?view=team&team=AVL"));
    await screen.findByRole("heading", { level: 2, name: "Aston Villa" });
    expect(cellsOf("Aston Villa")[0]).toHaveTextContent("20 Eyl Paz");
  });

  it("gives each week a club does not play a cell of its own", async () => {
    const errors = vi.spyOn(console, "error");
    serve(published(longRun()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=AVL"));
    await screen.findByRole("heading", { level: 2, name: "Aston Villa" });
    expect(cellsOf("Aston Villa")).toHaveLength(7);
    expect(errors).not.toHaveBeenCalled();
  });

  it("gives a double week two cells and runs on past the matrix's five", async () => {
    const errors = vi.spyOn(console, "error");
    const view = longRun();
    view.gameweeks
      .find((week) => week.gameweek === 9)!
      .fixtures.push(upcoming(99, BRE, ARS, "2026-10-21T14:00:00Z"));
    serve(published(view));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=ARS"));
    await screen.findByRole("heading", { level: 2, name: "Arsenal" });
    const printed = cellsOf("Arsenal").map((cell) => cell.querySelector(".week")!.textContent);
    expect(printed).toEqual(["GW3", "GW4", "GW5", "GW6", "GW7", "GW8", "GW9", "GW9"]);
    expect(errors).not.toHaveBeenCalled();
  });

  it("leaves no cell of one club in another's grid, through a week it does not play", async () => {
    const errors = vi.spyOn(console, "error");
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=AVL"));
    await screen.findByRole("heading", { level: 2, name: "Aston Villa" });
    expect(cellsOf("Aston Villa").map((cell) => cell.textContent)).toContain(
      `GW4${MESSAGES.en.leagueMembers.fixtureNone}`,
    );

    fireEvent.click(screen.getByRole("radio", { name: "ARS Arsenal" }));
    await screen.findByRole("heading", { level: 2, name: "Arsenal" });
    expect(cellsOf("Arsenal")).toHaveLength(2);
    expect(cellsOf("Arsenal")[0]).toHaveTextContent(new RegExp(`${FIXTURES_COPY.en.unscheduled}$`));

    fireEvent.click(screen.getByRole("radio", { name: "CHE Chelsea" }));
    await screen.findByRole("heading", { level: 2, name: "Chelsea" });
    expect(cellsOf("Chelsea")).toHaveLength(1);
    expect(errors).not.toHaveBeenCalled();
  });

  it("says so when the chosen club has nothing left, though the last week is still on", async () => {
    atClock("2026-09-26T16:00:00Z");
    serve(
      published({
        ...payload(null),
        captured_at_utc: "2026-09-26T15:00:00Z",
        gameweeks: [
          {
            gameweek: 4,
            deadline_utc: "2026-09-26T10:00:00Z",
            fixtures: [
              upcoming(6, BRE, ARS, "2026-09-26T14:00:00Z"),
              upcoming(7, CHE, AVL, "2026-09-27T14:00:00Z"),
            ],
          },
        ],
      }),
    );
    render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=ARS"));
    const heading = await screen.findByRole("heading", { level: 2, name: "Arsenal" });
    const region = heading.closest("section")!;
    expect(region).toHaveTextContent(`Arsenal${FIXTURES_COPY.en.noneAhead}`);
    expect(within(region).queryByRole("list")).toBeNull();
  });

  it.each(["XYZ", "bre", ""])("falls back to the first club for the unknown %j", async (team) => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", `/fixtures?view=team&team=${team}`));
    expect(await screen.findByRole("radio", { name: "ARS Arsenal" })).toBeChecked();
    expect(headings()).toEqual(["Arsenal"]);
  });

  it("keeps the chosen club while the view changes", async () => {
    serve(published(longRun()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    fireEvent.click(await screen.findByRole("radio", { name: FIXTURES_COPY.en.teamView }));
    fireEvent.click(screen.getByRole("radio", { name: "CHE Chelsea" }));
    expect(headings()).toEqual(["Chelsea"]);

    fireEvent.click(screen.getByRole("radio", { name: FIXTURES_COPY.en.generalView }));
    expect(await findMatrix()).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: FIXTURES_COPY.en.teamView }));
    expect(screen.getByRole("radio", { name: "CHE Chelsea" })).toBeChecked();
    expect(screen.getByTestId("address")).toHaveTextContent("/fixtures?team=CHE&view=team");
  });

  it("offers all twenty clubs of the shipped calendar, each with its code, colours and name", () => {
    // Drawn straight from the calendar: the page offers it only while a week is ahead.
    const clubs = fixtureClubs(shipped.payload);
    render(
      surface(
        <TeamFixtures
          payload={shipped.payload}
          clubs={clubs}
          club={clubs[0]!}
          onChoose={vi.fn()}
          copy={FIXTURES_COPY.tr}
        />,
        "tr",
        "/fixtures?view=team",
      ),
    );
    const group = screen.getByRole("group", { name: FIXTURES_COPY.tr.clubLegend });
    const labels = within(group)
      .getAllByRole("radio")
      .map((radio) => radio.closest("label")!);
    expect(labels.map((label) => label.textContent!.split(" ")[0])).toEqual(SEASON_CODES);
    for (const label of labels) {
      const [code, ...name] = label.textContent!.split(" ");
      expect(label).toHaveAttribute("title", name.join(" "));
      expect(
        label
          .querySelector<HTMLElement>("[aria-hidden='true']")!
          .style.getPropertyValue("--club-primary"),
      ).toBe(CLUB_COLOURS[code!]!.primary);
    }
  });
});

describe("what the fixtures page leaves out", () => {
  it.each(["tr", "en"] as const)(
    "prints no capture time and no deadline in either view in %s",
    async (language) => {
      serve(published(payload()));
      const first = render(surface(<FixturesPage />, language, "/fixtures"));
      await screen.findByRole("table", { name: FIXTURES_COPY[language].generalView });
      // The calendar file's button names the deadlines and prints none of them; the rest of
      // the page does not name them at all.
      const calendar = screen
        .getByTestId("surface")
        .querySelector('[data-mark="deadline-calendar"]')!;
      expect(calendar).toHaveTextContent(FIXTURES_COPY[language].calendarAction);
      expect(calendar.textContent).not.toMatch(/\d/);
      const words = () =>
        (screen.getByTestId("surface").textContent ?? "").replace(calendar.textContent ?? "", "");
      expect(words()).not.toMatch(/tarihli kayda göre|As recorded on|Son tarih|Deadline/);
      first.unmount();

      serve(published(payload()));
      render(surface(<FixturesPage />, language, "/fixtures?view=team"));
      await screen.findByRole("group", { name: FIXTURES_COPY[language].clubLegend });
      expect(screen.getByTestId("surface").textContent).not.toMatch(
        /tarihli kayda göre|As recorded on|Son tarih/,
      );
      expect(FIXTURES_COPY[language]).not.toHaveProperty("capturedAt");
      expect(FIXTURES_COPY[language]).not.toHaveProperty("deadline");
    },
  );

  it.each(["tr", "en"] as const)(
    "states the postponed fixtures in a paragraph of their own in %s, and nothing when none",
    async (language) => {
      serve(published(payload()));
      const first = render(surface(<FixturesPage />, language, "/fixtures"));
      const note = await screen.findByText(FIXTURES_COPY[language].unscheduledCount(1));
      expect(note.tagName).toBe("P");
      expect(note.textContent).toBe(FIXTURES_COPY[language].unscheduledCount(1));
      first.unmount();

      serve(published({ ...payload(), unscheduled_count: 0 }));
      render(surface(<FixturesPage />, language, "/fixtures"));
      await screen.findByRole("table", { name: FIXTURES_COPY[language].generalView });
      expect(screen.getByTestId("surface")).not.toHaveTextContent(
        FIXTURES_COPY[language].unscheduledCount(1),
      );
    },
  );

  describe("prints the fixtures and the choices, and not one word more", () => {
    const quiet = () => ({ ...payload(), unscheduled_count: 0 });
    const [kickoff, later] = ["2026-09-20T13:00:00Z", "2026-09-26T14:00:00Z"] as const;
    const day = (iso: string) => fixtureDay(iso, "en-GB");
    const time = (iso: string) => fixtureTime(iso, "en-GB");
    const copy = FIXTURES_COPY.en;
    const none = MESSAGES.en.leagueMembers.fixtureNone;
    const home = (code: string) => `${code}H${copy.atHome}`;
    const away = (code: string) => `${code}A${copy.away}`;
    // The names of the choices are in the text for assistive technology, though not on screen.
    const above = [
      "2026-27",
      copy.pageTitle,
      copy.calendarAction,
      copy.viewLegend,
      copy.generalView,
      copy.teamView,
    ];

    it("in the matrix", async () => {
      serve(published(quiet()));
      render(surface(<FixturesPage />, "en", "/fixtures"));
      const matrix = await findMatrix();
      expect(matrix.querySelector("caption")).toHaveClass("visually-hidden");
      expect(within(matrix).getAllByRole("columnheader")[0]!.firstElementChild).toHaveClass(
        "visually-hidden",
      );
      expect(screen.getByTestId("surface").querySelector("legend")).toHaveClass("visually-hidden");
      expect(screen.getByTestId("surface").textContent).toBe(
        [
          ...above,
          ...[copy.generalView, copy.clubLegend, "GW3", "GW4"],
          ...["ARSArsenal", `${away("CHE")}, ${copy.kickedOff}`, home("BRE"), away("BRE")],
          ...["AVLAston Villa", home("BRE"), none],
          ...["BREBrentford", away("AVL"), away("ARS"), home("ARS")],
          ...["CHEChelsea", `${home("ARS")}, ${copy.kickedOff}`, none],
        ].join(""),
      );
    });

    it("in the team view", async () => {
      serve(published(quiet()));
      render(surface(<FixturesPage />, "en", "/fixtures?view=team&team=BRE"));
      await screen.findByRole("heading", { level: 2, name: "Brentford" });
      expect(screen.getByTestId("surface").textContent).toBe(
        [
          ...above,
          copy.clubLegend,
          ...["ARS Arsenal", "AVL Aston Villa", "BRE Brentford", "CHE Chelsea"],
          "Brentford",
          `GW3A${copy.away}AVL Aston Villa${day(kickoff)}${time(kickoff)}`,
          `GW3A${copy.away}ARS Arsenal${copy.unscheduled}`,
          `GW4H${copy.atHome}ARS Arsenal${day(later)}${time(later)}`,
        ].join(""),
      );
    });
  });
});

describe("the two club colours in the matrix", () => {
  const week = shipped.payload.gameweeks[0]!;
  const matrixOf = (gameweek: FixturesPayload["gameweeks"][number], language: Language) =>
    surface(
      <FixtureMatrix
        payload={{ ...shipped.payload, gameweeks: [gameweek] }}
        weeks={[gameweek]}
        copy={FIXTURES_COPY[language]}
      />,
      language,
      "/fixtures",
    );

  it("covers all twenty clubs of the season in the shipped first gameweek", () => {
    const codes = week.fixtures.flatMap((fixture) => [
      fixture.home.short_name,
      fixture.away.short_name,
    ]);
    expect([...codes].sort()).toEqual(SEASON_CODES);
  });

  it.each(["tr", "en"] as const)(
    "draws both colours beside every club and opponent, with the code printed (%s)",
    (language) => {
      render(matrixOf(week, language));
      const painted = (holder: Element, code: string) => {
        const swatch = holder.querySelector<HTMLElement>("[aria-hidden='true']")!;
        expect(swatch.textContent).toBe("");
        expect(swatch.style.getPropertyValue("--club-primary")).toBe(CLUB_COLOURS[code]!.primary);
        expect(swatch.style.getPropertyValue("--club-secondary")).toBe(
          CLUB_COLOURS[code]!.secondary,
        );
      };
      const rows = screen.getAllByRole("rowheader");
      const clubs = rows.map((row) => row.querySelector(".clubCode")!.textContent!);
      expect(clubs).toEqual(SEASON_CODES);
      rows.forEach((row, index) => painted(row, clubs[index]!));

      const matches = [...document.querySelectorAll("[data-venue]")];
      const opponents = matches.map((match) => match.querySelector(".opponent")!.textContent!);
      expect([...opponents].sort()).toEqual(SEASON_CODES);
      matches.forEach((match, index) => painted(match, opponents[index]!));
    },
  );

  it("prints a club it has no colours for by its code alone", () => {
    const gameweek = {
      gameweek: 1,
      deadline_utc: "2026-08-21T17:30:00Z",
      fixtures: [upcoming(1, team(90, "Northport", "NPT"), ARS, "2026-08-22T14:00:00Z")],
    };
    render(matrixOf(gameweek, "en"));
    const match = lineOf(screen.getByRole("table"), "ARS")[0]!.querySelector("[data-venue]")!;
    expect(match.textContent).toBe(`NPTA${FIXTURES_COPY.en.away}, ${FIXTURES_COPY.en.kickedOff}`);
    // The venue letter is the only thing here hidden from assistive technology.
    expect(match.querySelectorAll("[aria-hidden='true']")).toHaveLength(1);
  });
});

describe("the fixture document", () => {
  const numbers = (weeks: readonly { gameweek: number }[]) => weeks.map((week) => week.gameweek);
  const instant = (iso: string) => Date.parse(iso);

  it("starts at the first week with its deadline open or a match still to kick off", () => {
    const view = payload();
    expect(numbers(weeksAhead(view, instant("2026-09-18T10:00:00Z")))).toEqual([3, 4]);
    // A closed FPL deadline does not hide fixtures still to be played this weekend.
    expect(numbers(weeksAhead(view, instant("2026-09-19T12:00:00Z")))).toEqual([3, 4]);
    expect(numbers(weeksAhead(view, instant("2026-09-22T12:00:00Z")))).toEqual([4]);
    expect(weeksAhead(view, instant("2027-01-01T00:00:00Z"))).toEqual([]);
    // No result is inferred from the clock.
    expect(view.gameweeks[2]!.fixtures[1]!.finished).toBe(false);
  });

  it.each([3, 4, null])("takes nothing from the capture's current gameweek (%s)", (current) => {
    const clock = instant("2026-09-19T12:00:00Z");
    expect(numbers(weeksAhead(payload(current), clock))).toEqual([3, 4]);
  });

  it("keeps an open week that has no fixture at all", () => {
    const view = payload();
    view.gameweeks.push({ gameweek: 5, deadline_utc: "2026-10-03T10:00:00Z", fixtures: [] });
    expect(numbers(weeksAhead(view, instant("2026-09-28T10:00:00Z")))).toEqual([5]);
    expect(numbers(weeksAhead(view, instant("2026-10-03T10:00:00Z")))).toEqual([]);
  });

  it("lets a fixture with no date hold no week open", () => {
    // Gameweek 3 still has ARS v BRE with no date; its deadline and its dated matches are past.
    expect(numbers(weeksAhead(payload(), instant("2026-09-22T12:00:00Z")))).toEqual([4]);
  });

  it("never reads the calendar earlier than its capture", () => {
    // The device says 1 August, when gameweek 1's deadline was ahead; the capture knows better.
    expect(numbers(weeksAhead(payload(), instant("2026-08-01T00:00:00Z")))).toEqual([3, 4]);
    const behind = instant("2026-08-01T00:00:00Z");
    expect(clubWeeksAhead(payload(), "AVL", behind)[0]!.matches).toHaveLength(1);
    const underway = { ...payload(), captured_at_utc: "2026-09-20T13:30:00Z" };
    underway.gameweeks[2]!.fixtures.push(upcoming(9, CHE, BRE, "2026-09-21T13:00:00Z"));
    expect(numbers(clubWeeksAhead(underway, "AVL", behind))).toEqual([4]);
    const [week3] = clubMatrix(underway, weeksAhead(underway, behind), behind)[1]!.cells;
    expect(week3!.map((match) => match.behind)).toEqual([true]);
  });

  it("goes by the device's clock when the capture's instant cannot be read", () => {
    const view = { ...payload(), captured_at_utc: "soon" };
    expect(numbers(weeksAhead(view, instant("2026-08-01T00:00:00Z")))).toEqual([1, 2, 3, 4]);
    expect(numbers(clubWeeksAhead(view, "AVL", instant("2026-09-18T10:00:00Z")))).toEqual([3, 4]);
  });

  it("reads the weeks in order, whatever order the document lists them in", () => {
    const view = payload();
    view.gameweeks.reverse();
    const listed = numbers(view.gameweeks);
    expect(numbers(weeksAhead(view))).toEqual([3, 4]);
    expect(numbers(view.gameweeks)).toEqual(listed);
  });

  it("counts the general view's five from the first week ahead, by number", () => {
    const ahead = weeksAhead(longRun());
    expect(numbers(ahead)).toEqual([3, 4, 5, 6, 7, 8, 9]);
    expect(numbers(generalWeeks(ahead))).toEqual([3, 4, 5, 6, 7]);
    expect(numbers(generalWeeks(ahead.filter((week) => week.gameweek !== 4)))).toEqual([
      3, 5, 6, 7,
    ]);
    expect(generalWeeks([])).toEqual([]);
  });

  it("names every club once, in the order of their codes", () => {
    const reversed = { ...payload(), gameweeks: payload().gameweeks.reverse() };
    expect(fixtureClubs(reversed).map((club) => club.short_name)).toEqual([
      "ARS",
      "AVL",
      "BRE",
      "CHE",
    ]);
    expect(fixtureClubs({ ...payload(), gameweeks: [] })).toEqual([]);
  });

  it("treats a match past its kickoff as behind the club, though the capture says unfinished", () => {
    const week = (code: string, now: string) =>
      clubWeeksAhead(payload(), code, instant(now)).map(({ gameweek, matches }) => [
        gameweek,
        matches.length,
      ]);
    expect(week("AVL", "2026-09-18T10:00:00Z")).toEqual([
      [3, 1],
      [4, 0],
    ]);
    expect(week("AVL", "2026-09-21T10:00:00Z")).toEqual([[4, 0]]);
    expect(week("AVL", "2026-09-20T13:00:00Z")).toEqual([[4, 0]]);
  });

  it("reads a finished match as behind, whatever its kickoff says", () => {
    const clock = instant("2026-09-22T12:00:00Z");
    const withThird = (fixture: Fixture) => {
      const view = payload();
      view.gameweeks[2]!.fixtures = [fixture];
      return view;
    };
    const dated = withThird({ ...played(3), kickoff_utc: "2026-09-25T13:00:00Z" });
    expect(numbers(weeksAhead(dated, clock))).toEqual([4]);
    const undated = withThird({ ...played(3), kickoff_utc: null });
    const [arsenal] = clubMatrix(undated, undated.gameweeks.slice(2, 3), clock);
    expect(arsenal!.cells[0]!.map((match) => match.behind)).toEqual([true]);
  });

  it("lines each club up over the weeks asked for, from its own side", () => {
    const view = payload();
    const weeks = weeksAhead(view, instant("2026-09-18T10:00:00Z"));
    const lines = clubMatrix(view, weeks, instant("2026-09-18T10:00:00Z"));
    expect(lines.map((line) => line.club.short_name)).toEqual(["ARS", "AVL", "BRE", "CHE"]);
    const brentford = lines[2]!.cells.map((cell) =>
      cell.map((match) => [match.opponent.short_name, match.home, match.behind]),
    );
    expect(brentford).toEqual([
      [
        ["AVL", false, false],
        ["ARS", false, false],
      ],
      [["ARS", true, false]],
    ]);
    expect(lines[1]!.cells[1]).toEqual([]);
    expect(lines[3]!.cells[0]!.map((match) => match.behind)).toEqual([true]);
  });

  it("reads the site-level path with the cache revalidated", async () => {
    const fetchMock = serve(published(payload()));
    expect((await loadFixtures())?.current_gameweek).toBe(3);
    expect(fetchMock).toHaveBeenCalledWith(
      "/data/fixtures.json",
      expect.objectContaining({ cache: "no-cache" }),
    );
  });

  it("is absent, not an error, when the transport fails or a row is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network");
      }),
    );
    expect(await loadFixtures()).toBeNull();
    const broken = payload();
    (broken.gameweeks[0]!.fixtures[0] as { home_score: unknown }).home_score = "3";
    serve(published(broken));
    expect(await loadFixtures()).toBeNull();
  });

  type Row = {
    current_gameweek: unknown;
    gameweeks: { gameweek: unknown; deadline_utc: unknown; fixtures: Record<string, unknown>[] }[];
  };
  it.each<[string, (doc: Row) => void]>([
    [
      "a club's code",
      (doc) => void (doc.gameweeks[0]!.fixtures[0]!.home = { name: "Arsenal", short_name: 1 }),
    ],
    ["a fixture's id", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.fixture_id = "1")],
    ["a kickoff", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.kickoff_utc = 1)],
    ["the home side", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.home = null)],
    ["the away side", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.away = null)],
    ["the finished flag", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.finished = "yes")],
    ["the away score", (doc) => void (doc.gameweeks[0]!.fixtures[0]!.away_score = "0")],
    ["a gameweek number", (doc) => void (doc.gameweeks[0]!.gameweek = "1")],
    ["a deadline", (doc) => void (doc.gameweeks[0]!.deadline_utc = null)],
    ["the current gameweek", (doc) => void (doc.current_gameweek = "3")],
  ])("is absent when %s is malformed", async (_field, breakIt) => {
    const broken = payload();
    breakIt(broken as unknown as Row);
    serve(published(broken));
    expect(await loadFixtures()).toBeNull();
  });

  it("is absent when not published, and reads the 404's body so the request ends", async () => {
    const response = new Response("<!doctype html><p>No document is published.</p>", {
      status: 404,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response),
    );
    expect(await loadFixtures()).toBeNull();
    expect(response.bodyUsed).toBe(true);
  });
});
