import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import indexFixture from "../../../../public/data/index.json";
import recommendationFixture from "../../../../public/data/2026-27/gw01/recommendation.json";
import type { DataClient, Loaded } from "../../../data/client";
import { NotFoundError } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { RecommendationView, SiteIndex } from "../../../data/schema";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { SquadPage } from "../pages/SquadPage";

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: "2026-08-19T10:00:00Z" };
}

function makeClient(deadlineUtc?: string): DataClient {
  return {
    getIndex: async () => loaded(indexFixture.payload as SiteIndex),
    getRecommendation: async (season, gameweek) => {
      if (season === "2026-27" && gameweek === 1) {
        const payload = recommendationFixture.payload as RecommendationView;
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
  { deadlineUtc, language = "tr" }: { deadlineUtc?: string; language?: Language } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const client = makeClient(deadlineUtc);
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
    const payload = recommendationFixture.payload as RecommendationView;
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
});
