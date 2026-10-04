/**
 * /league/<id> (where an old /league bookmark lands) shows the template ownership as the
 * game publishes it: the most and least owned starters, and no sentence naming the raw
 * capture field or what the page does not follow.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DataClient, Loaded } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { LeagueView, LedgerView, SiteIndex } from "../../../data/schema";
import { unsettledLedgerFixture } from "../../../fixtures/ledger";
import { unsettledRecommendationFixture } from "../../../fixtures/settledRecommendation";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { stubTree, withLeague } from "../../../testSupport/league";
import type { LeagueTree } from "../data";
import { LeagueDataMissing } from "../dataErrors";
import { LeaguePage } from "./LeaguePage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const [most, least] = unsettledRecommendationFixture.starting_xi;
const season = unsettledLedgerFixture.season;

const ledger: LedgerView = { ...unsettledLedgerFixture, decided_gameweeks: 0, rows: [] };

const league: LeagueView = {
  captured_at_utc: "2026-10-02T10:43:14Z",
  league_total_average_score: null,
  our_total_realized_net_score: null,
  ownership: {
    differential_threshold_percent: 10,
    differentials: [least!.player_id],
    effective_ownership: 313.1,
    gameweek: 5,
    least_owned_starter: least!.player_id,
    mean_starter_ownership: 21.8,
    most_owned_starter: most!.player_id,
    ownership_percent: { [String(most!.player_id)]: 61.2, [String(least!.player_id)]: 3.4 },
    squad: [most!, least!],
  },
  scored_gameweeks: 0,
  season,
  source_snapshot_id: "fpl-live-20261002T104314Z-8b70515b9b31",
  total_difference_to_average: null,
  verdict: "",
  weeks: [],
};

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: "2026-10-02T10:00:00Z" };
}

const client: DataClient = {
  getIndex: async () =>
    loaded({ latest: { season, gameweek: 5 }, seasons: [season] } as unknown as SiteIndex),
  getRecommendation: async () => {
    throw new Error("not used");
  },
  getPool: async () => {
    throw new Error("not used");
  },
  getLedger: async () => loaded(ledger),
  getLeague: async () => loaded(league),
  getStatus: async () => {
    throw new Error("not used");
  },
};

function renderLeague(language: Language) {
  stubTree({
    scoreboard: vi
      .fn<LeagueTree["scoreboard"]>()
      .mockRejectedValue(new LeagueDataMissing("scoreboard.json")),
  });
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <DataClientContext.Provider value={client}>
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter initialEntries={["/league/352490"]}>
            {withLeague(<LeaguePage />)}
          </MemoryRouter>
        </LanguageProvider>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("the league page in %s", (language) => {
  it("shows the template ownership with no caveat naming the capture's field", async () => {
    const { container } = renderLeague(language);
    const copy = MESSAGES[language].league;
    expect(await screen.findByText(copy.templateTitle)).toBeInTheDocument();
    expect(container).toHaveTextContent(copy.mostOwned);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/selected_by_percent/);
    expect(text).not.toMatch(/does not follow it|takip etmez/);
    expect(text).not.toMatch(AS_A_CHANCE);
  });
});
