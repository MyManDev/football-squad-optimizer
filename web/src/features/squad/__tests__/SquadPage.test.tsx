import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import indexFixture from "../../../../public/data/index.json";
import type { DataClient, Loaded } from "../../../data/client";
import { NotFoundError } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { RecommendationView, SiteIndex } from "../../../data/schema";
import {
  settledRecommendationFixture,
  unsettledRecommendationFixture,
} from "../../../fixtures/settledRecommendation";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { SquadPage } from "../pages/SquadPage";

afterEach(cleanup);

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: "2026-08-19T10:00:00Z" };
}

function makeClient(deadlineUtc?: string, viewOverride?: RecommendationView): DataClient {
  return {
    getIndex: async () => loaded(indexFixture.payload as SiteIndex),
    getRecommendation: async (season, gameweek) => {
      if (season === "2026-27" && gameweek === 1) {
        const payload = viewOverride ?? unsettledRecommendationFixture;
        return loaded({ ...payload, deadline_utc: deadlineUtc ?? payload.deadline_utc });
      }
      throw new NotFoundError(`${season}/gw${gameweek}`);
    },
    getPool: async () => {
      throw new Error("not used");
    },
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
}

function renderAt(
  path: string,
  {
    deadlineUtc,
    language = "tr",
    viewOverride,
  }: { deadlineUtc?: string; language?: Language; viewOverride?: RecommendationView } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const client = makeClient(deadlineUtc, viewOverride);
  return render(
    <QueryClientProvider client={queryClient}>
      <DataClientContext.Provider value={client}>
        <LanguageProvider initialLanguage={language}>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/" element={<SquadPage />} />
              <Route path="/gw/:season/:gameweek" element={<SquadPage />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

describe("SquadPage", () => {
  it("renders the latest decision from the site index", async () => {
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1/ }),
    ).toBeInTheDocument();
    const payload = unsettledRecommendationFixture;
    const captain = payload.starting_xi.find((p) => p.is_captain);
    expect(captain).toBeDefined();
    expect(screen.getAllByText(captain!.name).length).toBeGreaterThan(0);
    expect(screen.getByText(/Bu sayılar neyi söylemiyor/)).toBeInTheDocument();
    expect(screen.getByText(payload.risk.reason)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(payload.snapshot_id))).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Pozisyona göre ilk on bir" })).toBeInTheDocument();
    expect(screen.getByText(/oyuna giriş sırasıyla/)).toBeInTheDocument();
  });

  it("says plainly when a gameweek has no decision", async () => {
    renderAt("/gw/2026-27/7");
    expect(await screen.findByText(/Bu oyun haftası için karar yok/)).toBeInTheDocument();
  });

  it.each([
    { language: "tr", deadlineUtc: "2099-08-21T17:30:00Z", label: "son tarihe" },
    { language: "en", deadlineUtc: "2099-08-21T17:30:00Z", label: "deadline in" },
    { language: "tr", deadlineUtc: "2000-08-21T17:30:00Z", label: "son tarih" },
    { language: "en", deadlineUtc: "2000-08-21T17:30:00Z", label: "deadline" },
  ] as const)(
    "renders $label from countdown state in $language",
    async ({ deadlineUtc, label, language }) => {
      renderAt("/", { deadlineUtc, language });
      expect(await screen.findByText(label)).toBeInTheDocument();
    },
  );

  it("keeps the projection-outcome comparison hidden before settle", async () => {
    renderAt("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Oyun haftası 1" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Projeksiyon ve gerçekleşen")).not.toBeInTheDocument();
    expect(screen.queryByText(/event puanı/)).not.toBeInTheDocument();
  });

  it("shows settled totals, player event points and the captain multiplier", async () => {
    renderAt("/", {
      viewOverride: settledRecommendationFixture,
    });

    expect(await screen.findByText("Projeksiyon ve gerçekleşen")).toBeInTheDocument();
    expect(screen.getByText("gerçekleşen")).toBeInTheDocument();
    expect(
      screen.getAllByText(String(settledRecommendationFixture.outcome_realized_score)).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/^xP /)).toHaveLength(11);
    expect(screen.getAllByText(/^gerçekleşen /)).toHaveLength(11);
    expect(screen.getAllByText(/^fark /)).toHaveLength(11);
    expect(screen.getByText("×2 C")).toBeInTheDocument();
  });

  it("renders the contract captain multiplier instead of assuming two", async () => {
    const captain = settledRecommendationFixture.starting_xi.find((player) => player.is_captain)!;
    const tripleCaptain = {
      ...settledRecommendationFixture,
      captain_multiplier: 3,
      outcome_realized_score:
        settledRecommendationFixture.outcome_realized_score! + captain.event_points!,
      outcome_net_score: settledRecommendationFixture.outcome_net_score! + captain.event_points!,
    };
    renderAt("/", { viewOverride: tripleCaptain });

    expect(await screen.findByText("×3 C")).toBeInTheDocument();
  });
});
