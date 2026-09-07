import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NotFoundError, StaticDataClient } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { LiveScoreView } from "../../../data/liveScore";
import { liveScoreFixture } from "../../../fixtures/liveScore";
import { unsettledRecommendationFixture } from "../../../fixtures/settledRecommendation";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { LiveScoreCard } from "../components/LiveScoreCard";

afterEach(cleanup);

function show({
  payload = liveScoreFixture.payload,
  settled = false,
  now = "2026-08-23T18:00:00Z",
  error,
  language = "tr",
}: {
  payload?: LiveScoreView;
  settled?: boolean;
  now?: string;
  error?: Error;
  language?: Language;
} = {}) {
  const client = new StaticDataClient();
  client.getLiveScore = async () => {
    if (error) throw error;
    return { payload, generatedAtUtc: liveScoreFixture.generated_at_utc };
  };
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DataClientContext.Provider value={client}>
        <LanguageProvider initialLanguage={language}>
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
    expect(await screen.findByText(/seçili karar veya haftayla uyuşmuyor/)).toBeInTheDocument();
    expect(screen.queryByText("41")).not.toBeInTheDocument();
    expect(screen.queryByText(/synthetic-live-capture/)).not.toBeInTheDocument();
  });

  it("keeps older publications usable without a live document", async () => {
    show({ error: new NotFoundError("private/path/live.json") });
    expect(
      await screen.findByText("Bu hafta için canlı puan verisi bulunamadı."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/private\/path/)).not.toBeInTheDocument();
  });

  it.each([
    ["tr", "missing_payload", "Bu hafta için canlı puan verisi bulunamadı."],
    ["en", "missing_payload", "No live score data was found for this gameweek."],
    ["tr", "gameweek_mismatch", "Puan verisi seçili karar veya haftayla uyuşmuyor."],
    ["en", "gameweek_mismatch", "Score data does not match the selected decision or gameweek."],
    ["tr", "missing_players", "Puan verisi eksik veya doğrulanamadı."],
    ["en", "missing_players", "Score data is incomplete or could not be verified."],
  ] as const)("explains %s unavailable data: %s", async (language, reason, message) => {
    show({
      language,
      payload: {
        ...liveScoreFixture.payload,
        status: "unavailable",
        reason,
        named_score: null,
        net_score: null,
        transfer_hit_points: null,
        fixtures_finished: null,
        fixtures_total: null,
        bonus_confirmed: null,
      },
    });
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(screen.queryByText(/synthetic-live-capture/)).not.toBeInTheDocument();
  });

  it("falls back safely for unknown reasons", async () => {
    show({
      payload: { ...liveScoreFixture.payload, status: "unavailable", reason: "future-reason" },
    });
    expect(await screen.findByText(/Eksik veri sıfır puan değildir/)).toBeInTheDocument();
    expect(screen.queryByText(/future-reason|synthetic-live-capture|^41$/)).not.toBeInTheDocument();
  });

  it("does not guess the cause of an unclassified read error", async () => {
    show({ error: new Error("private network diagnostic: 404") });
    expect(await screen.findByText(/Eksik veri sıfır puan değildir/)).toBeInTheDocument();
    expect(screen.queryByText(/bulunamadı|private|network/)).not.toBeInTheDocument();
  });

  it("hides provisional scoring when settled", () => {
    const { container } = show({ settled: true });
    expect(container).toBeEmptyDOMElement();
  });
});
