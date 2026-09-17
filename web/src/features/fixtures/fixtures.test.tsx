import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AS_A_CHANCE } from "../../testSupport/honesty";
import { LanguageProvider } from "../../i18n/LanguageProvider";
import type { Language } from "../../i18n/messages";
import { fixtureWeeks, loadFixtures } from "./data";
import { FixturePanels } from "./FixturePanels";
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

/** The read has come back and the query has had its chance to render what it got. */
async function settled(fetchMock: ReturnType<typeof serve>) {
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 25));
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the fixture rails", () => {
  it.each(["tr", "en"] as const)(
    "show this week left and next week right in %s",
    async (language) => {
      serve(published(payload()));
      render(surface(<FixturePanels />, language));
      const copy = FIXTURES_COPY[language];

      const left = await screen.findByRole("complementary", { name: copy.thisWeek });
      expect(left).toHaveTextContent(language === "tr" ? "OH3" : "GW3");
      expect(left).toHaveTextContent(copy.deadline(""));
      expect(within(left).getAllByRole("listitem")).toHaveLength(3);

      const right = screen.getByRole("complementary", { name: copy.nextWeek });
      expect(right).toHaveTextContent(language === "tr" ? "OH4" : "GW4");
      expect(within(right).getAllByRole("listitem")).toHaveLength(1);
      expect(within(right).getByTitle("Brentford")).toHaveTextContent("BRE");

      for (const rail of [left, right]) {
        expect(within(rail).getByRole("link", { name: copy.pastLink })).toHaveAttribute(
          "href",
          "/fixtures",
        );
      }
    },
  );

  it("shows a finished fixture's score and an unfinished one's kickoff, never a score", async () => {
    serve(published(payload()));
    render(surface(<FixturePanels />));
    const left = await screen.findByRole("complementary", { name: "This week" });
    const [finished, scheduled] = within(left).getAllByRole("listitem");

    expect(finished).toHaveTextContent("CHE1 - 2ARS");
    expect(within(scheduled!).getByText(/^\d{2}:\d{2}$/)).toHaveAttribute(
      "datetime",
      "2026-09-20T13:00:00Z",
    );
    expect(scheduled).not.toHaveTextContent(/\d - \d/);
  });

  it("labels a fixture with no kickoff from the copy and prints no time for it", async () => {
    serve(published(payload()));
    render(surface(<FixturePanels />));
    const left = await screen.findByRole("complementary", { name: "This week" });
    expect(within(left).getByText(FIXTURES_COPY.en.unscheduled)).toBeInTheDocument();
    const row = within(left).getAllByRole("listitem")[2]!;
    expect(row).toHaveTextContent("ARSvBRE");
    expect(row.querySelector("time")).toBeNull();
  });

  it("keeps the same two lists closed under the page for a narrow screen", async () => {
    serve(published(payload()));
    const { container } = render(surface(<FixturePanels />));
    await screen.findByRole("complementary", { name: "This week" });
    const stacked = container.querySelector("details")!;
    expect(stacked.open).toBe(false);
    expect(within(stacked).getByText(FIXTURES_COPY.en.summary)).toBeInTheDocument();
    expect(stacked.querySelectorAll("li")).toHaveLength(4);
  });

  it("omits next week when the current gameweek is the last one published", async () => {
    serve(published(payload(4)));
    render(surface(<FixturePanels />));
    await screen.findByRole("complementary", { name: "This week" });
    expect(screen.queryByRole("complementary", { name: "Next week" })).toBeNull();
  });

  it.each([
    ["a 404", "Not found", 404],
    ["the host's HTML shell", "<!doctype html><html><body></body></html>", 200],
    ["another contract", JSON.stringify({ contract_version: "ui_view_v1", payload: {} }), 200],
    ["a document with no open gameweek", published(payload(null)), 200],
  ])("renders nothing for %s", async (_label, body, status) => {
    const fetchMock = serve(body, status);
    render(surface(<FixturePanels />));
    await settled(fetchMock);
    expect(screen.getByTestId("surface")).toBeEmptyDOMElement();
  });

  it("renders nothing on the fixtures page, which lists both weeks itself", async () => {
    const fetchMock = serve(published(payload()));
    render(surface(<FixturePanels />, "en", "/fixtures"));
    await settled(fetchMock);
    expect(screen.getByTestId("surface")).toBeEmptyDOMElement();
  });

  it("says nothing but schedule and result", async () => {
    serve(published(payload()));
    render(surface(<FixturePanels />, "tr"));
    await screen.findByRole("complementary", { name: FIXTURES_COPY.tr.thisWeek });
    expect(screen.getByTestId("surface").textContent).not.toMatch(AS_A_CHANCE);
  });
});

describe("the fixtures page", () => {
  it("lists this week and next first, then every played gameweek newest first", async () => {
    serve(published(payload()));
    render(surface(<FixturesPage />, "en", "/fixtures"));
    await screen.findByRole("heading", { level: 1, name: "Fixtures" });
    expect(screen.getAllByRole("heading", { level: 2 }).map((node) => node.textContent)).toEqual([
      "This week · Gameweek 3",
      "Next week · Gameweek 4",
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
});

describe("the fixture document", () => {
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
