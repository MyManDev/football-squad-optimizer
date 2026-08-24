import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import indexFixture from "../../../../public/data/index.json";
import type { DataClient, Loaded } from "../../../data/client";
import { NotFoundError } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { LedgerView, RecommendationView, SiteIndex } from "../../../data/schema";
import {
  hitLedgerFixture,
  pendingWeekLedgerFixture,
  settledLedgerFixture,
  unsettledLedgerFixture,
} from "../../../fixtures/ledger";
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

function makeClient(
  deadlineUtc?: string,
  viewOverride?: RecommendationView,
  ledger?: LedgerView,
): DataClient {
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
    // Left throwing by default on purpose: the season card must be additive, so every test
    // that does not opt in exercises the page with the ledger query failing.
    getLedger: async () => {
      if (ledger === undefined) throw new Error("not used");
      return loaded(ledger);
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
    ledger,
  }: {
    deadlineUtc?: string;
    language?: Language;
    viewOverride?: RecommendationView;
    ledger?: LedgerView;
  } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const client = makeClient(deadlineUtc, viewOverride, ledger);
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
    expect(
      screen.getByText("Artık geçmişi verilmedi; dağılımsal risk değerlendirilmedi."),
    ).toBeInTheDocument();
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
    expect(screen.queryByText("Projeksiyon ve Gerçekleşen")).not.toBeInTheDocument();
    expect(screen.queryByText(/event puanı/)).not.toBeInTheDocument();
  });

  it("shows settled totals, player event points and the captain multiplier", async () => {
    renderAt("/", {
      viewOverride: settledRecommendationFixture,
    });

    expect(await screen.findByText("Projeksiyon ve Gerçekleşen")).toBeInTheDocument();
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

describe("SquadPage season standing", () => {
  it("is absent until a gameweek has settled", async () => {
    renderAt("/", { ledger: unsettledLedgerFixture });

    expect(
      await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Sezon durumu")).not.toBeInTheDocument();
  });

  it("does not appear, and does not break the page, when the ledger cannot be read", async () => {
    renderAt("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Sezon durumu")).not.toBeInTheDocument();
  });

  it("reports the season total, the latest settled week and the projection gap", async () => {
    renderAt("/", { ledger: settledLedgerFixture });

    expect(await screen.findByText("Sezon durumu")).toBeInTheDocument();
    // With one settled week the season total and that week's points are the same number by
    // definition, so 61 legitimately appears twice — once per stat.
    expect(screen.getAllByText("61")).toHaveLength(2);
    expect(screen.getByText("1 hafta · 0 ceza puanı")).toBeInTheDocument();
    expect(screen.getByText(/^OH1 · tahmin 56,1$/)).toBeInTheDocument();
    expect(screen.getByText("+4,9")).toBeInTheDocument();
  });

  it("shows the net season total, not the gross one, when a hit was taken", async () => {
    renderAt("/", { ledger: hitLedgerFixture });

    expect(await screen.findByText("Sezon durumu")).toBeInTheDocument();
    // 111 gross, 107 net after a four-point hit. FPL shows 107, so this card must too.
    expect(screen.getByText("107")).toBeInTheDocument();
    expect(screen.queryByText("111")).not.toBeInTheDocument();
    expect(screen.getByText("2 hafta · 4 ceza puanı")).toBeInTheDocument();
  });

  it("reports the latest week with an outcome, not the latest decided week", async () => {
    renderAt("/", { ledger: pendingWeekLedgerFixture });

    expect(await screen.findByText("Sezon durumu")).toBeInTheDocument();
    // Gameweek three is decided but unsettled; its 46-point predecessor is the latest outcome.
    expect(screen.getByText(/^OH2 · tahmin 54,0$/)).toBeInTheDocument();
    expect(screen.getByText("46")).toBeInTheDocument();
  });

  it("labels the card in English too", async () => {
    renderAt("/", { language: "en", ledger: settledLedgerFixture });

    expect(await screen.findByText("Season standing")).toBeInTheDocument();
    expect(screen.getByText("1 settled · 0 hit points")).toBeInTheDocument();
    expect(screen.getByText(/^GW1 · projected 56.1$/)).toBeInTheDocument();
  });
});
