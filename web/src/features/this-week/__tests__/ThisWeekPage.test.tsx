import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import type { DataClient, Loaded } from "../../../data/client";
import { NotFoundError } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { RecommendationView, SiteIndex } from "../../../data/schema";
import indexFixture from "../../../../public/data/index.json";
import recommendationFixture from "../../../../public/data/2026-27/gw01/recommendation.json";
import { ThisWeekPage } from "../pages/ThisWeekPage";

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: "2026-08-19T10:00:00Z" };
}

const client: DataClient = {
  getIndex: async () => loaded(indexFixture.payload as SiteIndex),
  getRecommendation: async (season, gameweek) => {
    if (season === "2026-27" && gameweek === 1) {
      return loaded(recommendationFixture.payload as RecommendationView);
    }
    throw new NotFoundError(`${season}/gw${gameweek}`);
  },
  getPool: async () => {
    throw new Error("not used");
  },
  getLedger: async () => {
    throw new Error("not used");
  },
  getStatus: async () => {
    throw new Error("not used");
  },
};

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DataClientContext.Provider value={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<ThisWeekPage />} />
            <Route path="/gw/:season/:gameweek" element={<ThisWeekPage />} />
          </Routes>
        </MemoryRouter>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

describe("ThisWeekPage", () => {
  it("renders the latest decision from the site index", async () => {
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: /Gameweek 1/ }),
    ).toBeInTheDocument();
    const payload = recommendationFixture.payload as RecommendationView;
    const captain = payload.starting_xi.find((p) => p.is_captain);
    expect(captain).toBeDefined();
    expect(screen.getAllByText(captain!.name).length).toBeGreaterThan(0);
    // The honest risk state is on the page, in words.
    expect(screen.getByText(/What these numbers do not say/)).toBeInTheDocument();
    expect(screen.getByText(payload.risk.reason)).toBeInTheDocument();
    // Provenance is visible, not hidden in a tooltip.
    expect(screen.getByText(new RegExp(payload.snapshot_id))).toBeInTheDocument();
    // Eleven starters on the pitch, four on the bench.
    expect(screen.getByRole("list", { name: "Starting eleven by position" })).toBeInTheDocument();
    expect(screen.getByText(/in substitution order/)).toBeInTheDocument();
  });

  it("says plainly when a gameweek has no decision", async () => {
    renderAt("/gw/2026-27/7");
    expect(await screen.findByText(/No decision for this gameweek/)).toBeInTheDocument();
  });
});
