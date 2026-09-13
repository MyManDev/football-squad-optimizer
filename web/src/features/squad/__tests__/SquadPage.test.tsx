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
import { AS_A_CHANCE } from "../../../testSupport/honesty";
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

/**
 * A decision whose risk view really was evaluated: every metric the contract allows is a
 * number here, including the three the page must never publish. The published payload nulls
 * all of them, so without this fixture the risk block is dark in every test and a
 * probability could be reintroduced into it without one test going red.
 */
const fullyEvaluatedRisk: RecommendationView = {
  ...unsettledRecommendationFixture,
  risk: {
    blockers: [],
    location_shift_points: -3.2,
    lower_quantile_probability: 0.1,
    lower_quantile_score: 42.3,
    mean_score: 52.7,
    mean_worst_fraction_score: 31.4,
    points_threshold: 45,
    probability_below_threshold: 0.423,
    probability_below_threshold_interval: [0.312, 0.537],
    reason: "Risk metrics are supported by matched historical residual evidence.",
    residual_source: "midseason-residuals-2025-26",
    rivals: [],
    scenario_count: 1000,
    stated_limits: [
      "Scenarios are drawn from one season of residuals, and one season is a short history.",
    ],
    status: "available",
    worst_fraction: 0.1,
  },
};

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
    expect(screen.getByText(/Oyuna Giriş Sırasıyla/)).toBeInTheDocument();
  });

  it("puts no note under the projected score, and none in its place", async () => {
    renderAt("/");
    const label = await screen.findByText("Tahmini Puan");
    const stat = label.parentElement;
    expect(stat).not.toBeNull();
    // Stat renders label, value and, only when given one, a note. Two children means none.
    expect(stat!.children).toHaveLength(2);
    expect(screen.queryByText(/Kuyruk/)).not.toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "publishes no probability on the squad page in %s",
    async (language) => {
      const { container } = renderAt("/", { language });
      await screen.findByRole("heading", { level: 1 });
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
    },
  );

  it("says plainly when a gameweek has no decision", async () => {
    renderAt("/gw/2026-27/7");
    expect(await screen.findByText(/Bu oyun haftası için karar yok/)).toBeInTheDocument();
  });

  it.each([
    { language: "tr", deadlineUtc: "2099-08-21T17:30:00Z", label: "Son Tarihe" },
    { language: "en", deadlineUtc: "2099-08-21T17:30:00Z", label: "Deadline In" },
    { language: "tr", deadlineUtc: "2000-08-21T17:30:00Z", label: "Son Tarih" },
    { language: "en", deadlineUtc: "2000-08-21T17:30:00Z", label: "Deadline" },
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
    expect(screen.getByText("Gerçekleşen")).toBeInTheDocument();
    expect(
      screen.getAllByText(String(settledRecommendationFixture.outcome_realized_score)).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/^xP /)).toHaveLength(11);
    expect(screen.getAllByText(/^Gerçekleşen /)).toHaveLength(11);
    expect(screen.getAllByText(/^Fark /)).toHaveLength(11);
    expect(screen.getByText("×2 C")).toBeInTheDocument();
  });

  it.each(["tr", "en"] as const)(
    "opens no risk block on a status with no metrics behind it, in %s",
    async (language) => {
      // The frozen ledger records the status and nulls every metric. Opening the block on
      // the status alone printed an absent worst-case share as 0% and a P(...) label with
      // a literal "?" for a threshold nobody measured.
      const withStatus: RecommendationView = {
        ...unsettledRecommendationFixture,
        risk: { ...unsettledRecommendationFixture.risk, status: "available" },
      };
      const { container } = renderAt("/", { viewOverride: withStatus, language });

      expect(
        await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1|Gameweek 1/ }),
      ).toBeInTheDocument();
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/P\(/);
      expect(text).not.toMatch(/%/);
      expect(text).not.toMatch(/Senaryo Ortalaması|Mean of Scenarios/);
    },
  );

  it.each(["tr", "en"] as const)(
    "publishes no probability when every risk metric IS populated, in %s",
    async (language) => {
      // The published payload nulls every risk metric, so the ordinary fixture leaves this
      // block dark and cannot see what it would print. This one populates all of them. The
      // forbidden wording here lives in the rendered values, not in a copy key, so the
      // catalogue sweep cannot reach it and only a render can.
      const { container } = renderAt("/", { viewOverride: fullyEvaluatedRisk, language });

      expect(
        await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1|Gameweek 1/ }),
      ).toBeInTheDocument();
      const text = container.textContent ?? "";
      expect(text).not.toMatch(AS_A_CHANCE);
      expect(text).not.toMatch(/%/);
      expect(text).not.toMatch(/P\(/);
      // The numbers themselves, not only their labels: no metric may reach the page as a
      // share, and no quantile score may reach it at all.
      for (const forbidden of ["42", "31.4", "31,4", "0.423", "0,423", "10%", "%10", "90%", "%90"])
        expect(text).not.toContain(forbidden);
    },
  );

  it.each([
    { language: "tr", mean: "52,7", shift: "Seçim İyimserliği İçin -3,2 Kaydırıldı" },
    { language: "en", mean: "52.7", shift: "Shifted -3.2 for Selection Optimism" },
  ] as const)(
    "keeps what is not distributional in $language",
    async ({ language, mean, shift }) => {
      const { container } = renderAt("/", { viewOverride: fullyEvaluatedRisk, language });

      expect(
        await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1|Gameweek 1/ }),
      ).toBeInTheDocument();
      const text = container.textContent ?? "";
      // The mean of the scenarios is expected points, the shift is points, and the scenario
      // count is a count. None of the three is a probability, a quantile or a spread.
      expect(text).toContain(mean);
      expect(text).toContain(shift);
      expect(text).toContain(language === "tr" ? "1000 Senaryo" : "1000 Scenarios");
      expect(container.textContent).toContain(
        language === "tr" ? "Senaryo Ortalaması" : "Mean of Scenarios",
      );
    },
  );

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
    expect(screen.queryByText("Sezon Durumu")).not.toBeInTheDocument();
  });

  it("does not appear, and does not break the page, when the ledger cannot be read", async () => {
    renderAt("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: /Oyun haftası 1/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Sezon Durumu")).not.toBeInTheDocument();
  });

  it("reports the season total, the latest settled week and the projection gap", async () => {
    renderAt("/", { ledger: settledLedgerFixture });

    expect(await screen.findByText("Sezon Durumu")).toBeInTheDocument();
    // With one settled week the season total and that week's points are the same number by
    // definition, so 61 legitimately appears twice — once per stat.
    expect(screen.getAllByText("61")).toHaveLength(2);
    expect(screen.getByText("1 Hafta · 0 Ceza Puanı")).toBeInTheDocument();
    expect(screen.getByText(/^OH1 · Tahmin 56,1$/)).toBeInTheDocument();
    expect(screen.getByText("+4,9")).toBeInTheDocument();
  });

  it("shows the net season total, not the gross one, when a hit was taken", async () => {
    renderAt("/", { ledger: hitLedgerFixture });

    expect(await screen.findByText("Sezon Durumu")).toBeInTheDocument();
    // 111 gross, 107 net after a four-point hit. FPL shows 107, so this card must too.
    expect(screen.getByText("107")).toBeInTheDocument();
    expect(screen.queryByText("111")).not.toBeInTheDocument();
    expect(screen.getByText("2 Hafta · 4 Ceza Puanı")).toBeInTheDocument();
  });

  it("reports the latest week with an outcome, not the latest decided week", async () => {
    renderAt("/", { ledger: pendingWeekLedgerFixture });

    expect(await screen.findByText("Sezon Durumu")).toBeInTheDocument();
    // Gameweek three is decided but unsettled; its 46-point predecessor is the latest outcome.
    expect(screen.getByText(/^OH2 · Tahmin 54,0$/)).toBeInTheDocument();
    expect(screen.getByText("46")).toBeInTheDocument();
  });

  it("labels the card in English too", async () => {
    renderAt("/", { language: "en", ledger: settledLedgerFixture });

    expect(await screen.findByText("Season Standing")).toBeInTheDocument();
    expect(screen.getByText("1 Settled · 0 Hit Points")).toBeInTheDocument();
    expect(screen.getByText(/^GW1 · Projected 56.1$/)).toBeInTheDocument();
  });
});
