import { useEffect, useMemo } from "react";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import { createAdviceClient, type AdviceClient, type AdviceRequest } from "./adviceClient";
import { sameAdviceRequest, useAdviceJob } from "./useAdviceJob";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { checkedAdvice } from "./adviceResponse";

/** Same inputs under both models; computing the other answer requires a click. */
export function ModelComparison({
  request,
  selected,
  snapshot,
  client,
  busy = false,
  deadlinePassed = false,
}: {
  request: AdviceRequest;
  selected: LeagueViewEnvelope<EntryAdvice> | null;
  snapshot?: string | null;
  client?: AdviceClient;
  busy?: boolean;
  deadlinePassed?: boolean;
}) {
  const { language, messages } = useLanguage();
  const tr = language === "tr";
  // The Top 100 setting is a weight on the selection, never a share of anything.
  const weight = messages.leagueMembers.top100Weight(request.top100Weight ?? 0);
  const transport = useMemo(() => client ?? createAdviceClient(), [client]);
  const {
    leagueId,
    entryId,
    strategy,
    window,
    rivalEntryId,
    top100Weight,
    managersWord,
    chip,
    season,
    gameweek,
    model,
  } = request;
  const other = useMemo<AdviceRequest>(
    () => ({
      leagueId,
      entryId,
      strategy,
      window,
      rivalEntryId,
      top100Weight,
      managersWord,
      chip,
      season,
      gameweek,
      model: model === "football" ? "current" : "football",
    }),
    [
      leagueId,
      entryId,
      strategy,
      window,
      rivalEntryId,
      top100Weight,
      managersWord,
      chip,
      season,
      gameweek,
      model,
    ],
  );
  const job = useAdviceJob(transport, false, snapshot);
  const { reset, readCached, resume } = job;
  useEffect(() => {
    reset();
    if (!resume?.(other)) readCached?.(other);
  }, [other, reset, readCached, resume]);
  const state = job.state;
  const matched = state.phase !== "idle" && sameAdviceRequest(state.request, other);
  const counterpart = matched && state.phase === "done" ? state.envelope.payload : null;
  const waiting = matched && (state.phase === "requesting" || state.phase === "waiting");
  let selectedPayload: EntryAdvice | null = null;
  try {
    if (selected) {
      const valid = checkedAdvice(selected, request).payload;
      if (snapshot == null || valid.source_snapshot_id === snapshot) selectedPayload = valid;
    }
  } catch {
    // A baseline shown while waiting does not answer the comparison's settings.
  }
  const current = request.model === "football" ? counterpart : selectedPayload;
  const football = request.model === "football" ? selectedPayload : counterpart;
  const display = (value: unknown) => (typeof value === "number" ? value.toFixed(2) : "—");
  return (
    <Card title={tr ? "İki modelin karşılaştırması" : "Model comparison"}>
      <p>
        {tr
          ? `Aynı kadro, bütçe, ${request.window} hafta ve ${weight}.`
          : `Same squad, budget, ${request.window} weeks and ${weight}.`}
      </p>
      <table style={{ width: "100%" }}>
        <thead>
          <tr>
            <th scope="col">{tr ? "Sonuç" : "Result"}</th>
            <th scope="col">{tr ? "Mevcut" : "Current"}</th>
            <th scope="col">{tr ? "Futbol · Deneysel" : "Football · Experimental"}</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">{tr ? "İlk hafta beklenen puan" : "First-week expected points"}</th>
            <td>{display(current?.expected_own_points)}</td>
            <td>{display(football?.expected_own_points)}</td>
          </tr>
          <tr>
            <th scope="row">{tr ? "Kaptan" : "Captain"}</th>
            <td>{current?.captain?.name ?? "—"}</td>
            <td>{football?.captain?.name ?? "—"}</td>
          </tr>
          <tr>
            <th scope="row">{tr ? "Transfer" : "Transfers"}</th>
            <td>{current?.moves.length ?? "—"}</td>
            <td>{football?.moves.length ?? "—"}</td>
          </tr>
        </tbody>
      </table>
      <p>
        {tr
          ? "Puanlar her modelin kendi tahminidir; yüksek sayı daha başarılı model demek değildir. Başarı, ileride gerçekleşen sonuçlarla ölçülecek."
          : "Each score is its model's estimate; a larger number does not prove greater accuracy. Success needs future observed outcomes."}
      </p>
      {!counterpart && (
        <button
          type="button"
          disabled={busy || waiting || deadlinePassed}
          onClick={() => job.compute(other)}
        >
          {waiting
            ? tr
              ? "Diğer model hesaplanıyor…"
              : "Computing other model…"
            : tr
              ? "Diğer modeli de hesapla"
              : "Compute the other model"}
        </button>
      )}
      {deadlinePassed && (
        <p role="note">
          {tr
            ? "Bu haftanın son karar tarihi geçti; yeni hesaplama kapalı."
            : "This gameweek's deadline has passed; new computations are closed."}
        </p>
      )}
      {matched && state.phase === "failed" && (
        <p role="status">
          {tr
            ? "Diğer modelin sonucu alınamadı. Yeniden deneyebilirsiniz."
            : "The other result could not be retrieved. You can retry."}
        </p>
      )}
    </Card>
  );
}
