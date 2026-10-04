/**
 * /rivals says why no rival is scored against the decision, and says it without naming a
 * probability: the projections below are what the page shows, and nothing is set against
 * a chance nobody measured.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import type { DataClient, Loaded } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { PoolView, SiteIndex } from "../../../data/schema";
import { unsettledRecommendationFixture } from "../../../fixtures/settledRecommendation";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { RivalsPage } from "./RivalsPage";

afterEach(cleanup);

const view = {
  ...unsettledRecommendationFixture,
  risk: { ...unsettledRecommendationFixture.risk, status: "not_requested" as const },
};

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: "2026-10-02T10:00:00Z" };
}

const client: DataClient = {
  getIndex: async () =>
    loaded({
      latest: { season: view.season, gameweek: view.gameweek },
      seasons: [view.season],
    } as unknown as SiteIndex),
  getRecommendation: async () => loaded(view),
  getPool: async () =>
    loaded<PoolView>({
      season: view.season,
      gameweek: view.gameweek,
      pool_size: 0,
      per_position: 0,
      players: [],
    }),
  getLedger: async () => {
    throw new Error("not used");
  },
  getLeague: async () => {
    throw new Error("not used");
  },
  getStatus: async () => {
    throw new Error("not used");
  },
};

function renderRivals(language: Language) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <DataClientContext.Provider value={client}>
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter initialEntries={["/rivals"]}>
            <Routes>
              <Route path="/rivals" element={<RivalsPage />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

describe.each(["tr", "en"] as const)("the rivals page in %s", (language) => {
  it("says no rival was scored without naming a probability", async () => {
    const { container } = renderRivals(language);
    const copy = MESSAGES[language].rivals;
    expect(await screen.findByText(copy.noRivalTitle)).toBeInTheDocument();
    expect(container).toHaveTextContent(copy.noRivalAfterStatus.trim());
    expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
    expect(container.textContent ?? "").not.toMatch(/olasılık|probability/i);
  });
});
