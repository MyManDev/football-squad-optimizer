import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StaticDataClient } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { LiveScoreView } from "../../../data/liveScore";
import { liveScoreFixture } from "../../../fixtures/liveScore";
import { unsettledRecommendationFixture } from "../../../fixtures/settledRecommendation";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { LiveScoreCard } from "../components/LiveScoreCard";

afterEach(cleanup);

function show({
  payload = liveScoreFixture.payload,
  settled = false,
  now = "2026-08-23T18:00:00Z",
  missing = false,
}: { payload?: LiveScoreView; settled?: boolean; now?: string; missing?: boolean } = {}) {
  const client = new StaticDataClient();
  client.getLiveScore = async () => {
    if (missing) throw new Error("404");
    return { payload, generatedAtUtc: liveScoreFixture.generated_at_utc };
  };
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DataClientContext.Provider value={client}>
        <LanguageProvider initialLanguage="tr">
          <LiveScoreCard
            view={{ ...unsettledRecommendationFixture, settled }}
            now={new Date(now)}
          />
        </LanguageProvider>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

describe("LiveScoreCard", () => {
  it("keeps provisional score, progress, bonus and capture together", async () => {
    show();
    expect(await screen.findByText("41")).toBeInTheDocument();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("4 / 10")).toBeInTheDocument();
    expect(screen.getByText(/Bonus henüz onaylanmadı/)).toBeInTheDocument();
    expect(screen.getByText(/synthetic-live-capture/)).toBeInTheDocument();
    expect(screen.getByText(/4 transfer cezası bir kez/)).toBeInTheDocument();
    expect(screen.getByText(/yardımcı kaptana geçiş uygulanmaz/)).toBeInTheDocument();
  });

  it("marks an old capture even when its document was just generated", async () => {
    show({ now: "2026-08-24T18:00:00Z" });
    expect(await screen.findByText(/Eski capture/)).toBeInTheDocument();
    expect(screen.getByText("41")).toBeInTheDocument();
  });

  it("carries confirmed bonus while staying provisional", async () => {
    show({
      payload: { ...liveScoreFixture.payload, fixtures_finished: 10, bonus_confirmed: true },
    });
    expect(await screen.findByText("Kaynakta bonus onaylandı")).toBeInTheDocument();
    expect(screen.getByText("Geçici")).toBeInTheDocument();
  });

  it.each([
    { gameweek: 2 },
    { season: "2025-26" },
    { decision_snapshot_id: "another-decision" },
    { prediction_fingerprint: "another-projection" },
  ])("does not carry another decision's score: %j", async (patch) => {
    show({ payload: { ...liveScoreFixture.payload, ...patch } });
    expect(await screen.findByText(/Eksik veri sıfır puan değildir/)).toBeInTheDocument();
    expect(screen.queryByText("41")).not.toBeInTheDocument();
  });

  it("keeps older publications usable without a live document", async () => {
    show({ missing: true });
    expect(await screen.findByText(/Eksik veri sıfır puan değildir/)).toBeInTheDocument();
  });

  it("hides provisional scoring when settled", () => {
    const { container } = show({ settled: true });
    expect(container).toBeEmptyDOMElement();
  });
});
