import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { stubTree, withLeague } from "../../../testSupport/league";
import { FIXTURES_QUERY } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { LeagueDataMissing } from "../data";
import { leagueKeys } from "../queries";
import { LeagueMemberPage } from "./LeagueMemberPage";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("rolls the open tab's closed rail at the exact module boundary while the top bar keeps P", async () => {
  const entry = 35249001;
  const squad = mockEntrySquadEnvelopes[entry]!;
  const p = squad.payload.gameweek;
  const league = squad.payload.league_id;
  const end = Date.parse("2026-11-21T15:30:00Z");
  vi.useFakeTimers({
    toFake: ["Date", "setInterval", "clearInterval", "setTimeout", "clearTimeout"],
  });
  vi.setSystemTime(end - 1_000);
  const team = { team_id: 1, name: "Arsenal", short_name: "ARS" };
  const calendar: FixturesPayload = {
    season: squad.payload.season,
    source_snapshot_id: "synthetic-member-week",
    captured_at_utc: "2026-11-20T00:00:00Z",
    current_gameweek: p,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: p,
        deadline_utc: "2026-11-21T11:00:00Z",
        fixtures: [
          {
            fixture_id: 1,
            kickoff_utc: "2026-11-21T12:30:00Z",
            finished: false,
            home: team,
            away: { team_id: 2, name: "Aston Villa", short_name: "AVL" },
            home_score: null,
            away_score: null,
          },
        ],
      },
      { gameweek: p + 1, deadline_utc: "2026-11-28T11:00:00Z", fixtures: [] },
      { gameweek: p + 2, deadline_utc: "2026-12-05T11:00:00Z", fixtures: [] },
    ],
  };
  const index = mockEntryAdviceIndex(entry);
  stubTree({
    entrySquad: async () => squad,
    members: async () => mockLeagueMembersEnvelope,
    entryAdviceIndex: async () => index,
    entryAdvice: async () => mockEntryAdviceEnvelope(entry, "saf-puan", 1),
    scoreboard: async () => {
      throw new LeagueDataMissing("synthetic-scoreboard.json");
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("Not found", { status: 404 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(leagueKeys.entrySquad(league, entry), squad);
  client.setQueryData(leagueKeys.members(league), mockLeagueMembersEnvelope);
  client.setQueryData(leagueKeys.adviceIndex(league, entry), index);
  client.setQueryData(FIXTURES_QUERY.queryKey, calendar);
  try {
    const shown = render(
      <QueryClientProvider client={client}>
        <LanguageProvider initialLanguage="en">
          <MemoryRouter initialEntries={[`/league/${league}/members/${entry}`]}>
            <Routes>
              <Route
                path="/league/:leagueId/members/:entryId"
                element={withLeague(<LeagueMemberPage />)}
              />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const rail = () => shown.container.querySelector<HTMLElement>('[data-zone="fixtures-rail"]')!;
    const hasWeek = (week: number) =>
      within(rail()).queryAllByRole("columnheader", {
        name: MESSAGES.en.leagueMembers.railWeekColumn(week),
      }).length > 0;
    const bar = shown.container.querySelector<HTMLElement>('header[data-zone="topbar"]')!;
    expect(hasWeek(p)).toBe(true);
    expect(bar).toHaveTextContent(MESSAGES.en.leagueMembers.weekLabel(p));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(hasWeek(p)).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(hasWeek(p)).toBe(false);
    expect(hasWeek(p + 1)).toBe(true);
    expect(bar).toHaveTextContent(MESSAGES.en.leagueMembers.weekLabel(p));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(hasWeek(p)).toBe(false);
    expect(hasWeek(p + 1)).toBe(true);
    expect(bar).toHaveTextContent(MESSAGES.en.leagueMembers.weekLabel(p));
    await act(async () => {
      client.setQueryData(FIXTURES_QUERY.queryKey, {
        ...calendar,
        gameweeks: calendar.gameweeks.slice(0, 1),
      });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(shown.container.querySelector('[data-zone="fixtures-rail"]')).toBeNull();
    expect(bar).toHaveTextContent(MESSAGES.en.leagueMembers.weekLabel(p));
  } finally {
    cleanup();
    client.clear();
  }
});
