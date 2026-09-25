import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PageShell } from "../../design/components/PageShell";
import { AS_A_CHANCE } from "../../testSupport/honesty";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../i18n/messages";
import { fixtureWeeks, upcomingFixtureWeeks, loadFixtures } from "./data";
import { FIXTURES_COPY } from "./fixturesCopy";
import { FixturesPage } from "./FixturesPage";
import type { Fixture, FixturesPayload } from "./types";

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

function serve(body: string, status = 200) {
  const fetchMock = vi.fn(async () => new Response(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const published = (view: FixturesPayload) =>
  JSON.stringify({ contract_version: "fixtures_v1", generated_at_utc: "now", payload: view });

function surface(node: React.ReactNode, language: Language = "en", path = "/league/members/1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <LanguageProvider initialLanguage={language}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <div data-testid="surface">{node}</div>
        </MemoryRouter>
      </QueryClientProvider>
    </LanguageProvider>
  );
}

/** The region the fixtures page gives one gameweek, found by its heading. */
async function gameweekRegion(name: string) {
  const heading = await screen.findByRole("heading", { level: 2, name });
  return heading.closest("section")!;
}

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
          "/gw/2026-27/1",
        ),
      );
      const copy = FIXTURES_COPY[language];
      const shell = MESSAGES[language].shell;

      // The two margin rails and the closed list under the page are gone: the member page
      // carries its own fixtures, and /fixtures carries the whole list.
      expect(screen.queryByRole("complementary", { name: copy.thisWeek })).toBeNull();
      expect(screen.queryByRole("complementary", { name: copy.nextWeek })).toBeNull();
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
  it("lists this week and next first, then every played gameweek newest first", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    await screen.findByRole("heading", { level: 1, name: "Fixtures" });
    expect(screen.getAllByRole("heading", { level: 2 }).map((node) => node.textContent)).toEqual([
      "Upcoming gameweek · Gameweek 3",
      "Following gameweek · Gameweek 4",
      "Past gameweeks",
      "Gameweek 2",
      "Gameweek 1",
    ]);
    const goalless = screen.getByRole("heading", { level: 2, name: "Gameweek 2" });
    expect(goalless.closest("section")).toHaveTextContent("BRE0 - 0CHE");
    expect(screen.getByTestId("surface")).toHaveTextContent(FIXTURES_COPY.en.unscheduledCount(1));
  });

  it("says so when no fixture list is published", async () => {
    serve("Not found", 404);
    render(surface(<FixturesPage />, "tr", "/fixtures"));
    expect(await screen.findByText(FIXTURES_COPY.tr.notPublished)).toBeInTheDocument();
  });

  it.each([
    ["the host's HTML shell", "<!doctype html><html><body></body></html>"],
    ["another contract", JSON.stringify({ contract_version: "ui_view_v1", payload: {} })],
  ])("treats %s as no fixture list, not as an error", async (_label, body) => {
    serve(body);
    render(surface(<FixturesPage />, "en", "/fixtures"));
    expect(await screen.findByText(FIXTURES_COPY.en.notPublished)).toBeInTheDocument();
  });

  it("shows a finished fixture's score and an unfinished one's kickoff, never a score", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const week = await gameweekRegion("Upcoming gameweek · Gameweek 3");
    const [finished, scheduled] = within(week).getAllByRole("listitem");

    expect(finished).toHaveTextContent("CHE1 - 2ARS");
    expect(within(scheduled!).getByText(/^\d{2}:\d{2}$/)).toHaveAttribute(
      "datetime",
      "2026-09-20T13:00:00Z",
    );
    expect(scheduled).not.toHaveTextContent(/\d - \d/);
  });

  it("labels a fixture with no kickoff from the copy and prints no time for it", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    const week = await gameweekRegion("Upcoming gameweek · Gameweek 3");
    expect(within(week).getByText(FIXTURES_COPY.en.unscheduled)).toBeInTheDocument();
    const row = within(week).getAllByRole("listitem")[2]!;
    expect(row).toHaveTextContent("ARSvBRE");
    expect(row.querySelector("time")).toBeNull();
  });

  it("omits next week when the current gameweek is the last one published", async () => {
    serve(published(payload(4)));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    await gameweekRegion("Upcoming gameweek · Gameweek 4");
    expect(screen.queryByRole("heading", { level: 2, name: /^Following gameweek/ })).toBeNull();
  });

  it("names no upcoming week once no deadline is open", async () => {
    serve(published(payload(null)));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    await gameweekRegion("Gameweek 4");
    expect(screen.queryByRole("heading", { level: 2, name: /^Upcoming gameweek/ })).toBeNull();
  });

  it("says nothing but schedule and result", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "tr", "/fixtures"));
    await gameweekRegion(`${FIXTURES_COPY.tr.thisWeek} · Oyun haftası 3`);
    expect(screen.getByTestId("surface").textContent).not.toMatch(AS_A_CHANCE);
  });
});

describe("the fixture document", () => {
  it("advances an old capture to the next open deadline without inventing scores", () => {
    const view = payload();
    const upcoming = upcomingFixtureWeeks(view, Date.parse("2026-09-22T12:00:00Z"));
    expect(upcoming.current?.gameweek).toBe(4);
    expect(upcoming.next).toBeNull();
    expect(view.current_gameweek).toBe(3);
    // A closed FPL deadline does not hide fixtures still to be played this weekend.
    expect(upcomingFixtureWeeks(view, Date.parse("2026-09-19T12:00:00Z")).current?.gameweek).toBe(
      3,
    );
    expect(view.gameweeks[2]!.fixtures[1]!.finished).toBe(false);
    expect(upcomingFixtureWeeks(view, Date.parse("2027-01-01T00:00:00Z")).current).toBeNull();
  });
  it("rolls by itself: a later current gameweek moves next to current and current to past", () => {
    const before = fixtureWeeks(payload(3));
    const after = fixtureWeeks(payload(4));
    expect(before.next?.gameweek).toBe(4);
    expect(after.current?.gameweek).toBe(4);
    expect(after.next).toBeNull();
    expect(after.past.map((week) => week.gameweek)).toEqual([3, 2, 1]);
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
});
