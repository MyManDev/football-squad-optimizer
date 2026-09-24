import { useState } from "react";
import { useSearchParams } from "react-router";
import { Card } from "../../../design/components/Card";
import { useLanguage } from "../../../i18n/context";
import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "./adviceClient";
import {
  decisionCandidate,
  decisionMetrics,
  decisionParams,
  loadDecisionBoard,
  saveDecisionBoard,
  type DecisionBoardState,
} from "./decisionBoard";
import styles from "./DecisionWorkbench.module.css";

/** A personal choice among computed plans, never an automatic model promotion. */
type Props = {
  request: AdviceRequest;
  selected: LeagueViewEnvelope<EntryAdvice> | null;
  squad: LeagueViewEnvelope<EntrySquad>;
  loading?: boolean;
};

export function DecisionWorkbench(props: Props) {
  return <DecisionWorkbenchContent key={JSON.stringify(props.squad)} {...props} />;
}

function DecisionWorkbenchContent({ request, selected, squad, loading = false }: Props) {
  const { language, messages } = useLanguage();
  const tr = language === "tr";
  const [params, setParams] = useSearchParams();
  const [board, setBoard] = useState(() => loadDecisionBoard(squad));
  const [stored, setStored] = useState(true);
  const candidate = loading ? null : decisionCandidate(selected, request, squad);
  const pinned = candidate && board.candidates.some((c) => c.id === candidate.id);
  function change(next: DecisionBoardState) {
    setBoard(next);
    setStored(saveDecisionBoard(squad, next));
  }
  const number = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));
  const chipName = (chip: string | null | undefined) =>
    chip === "auto"
      ? tr
        ? "Otomatik"
        : "Automatic"
      : chip
        ? (messages.leagueMembers.chipNames[chip] ?? chip)
        : tr
          ? "Sakla"
          : "Hold";
  return (
    <Card title={tr ? "Karar masam" : "My decision board"}>
      <p>
        {tr
          ? "Bir planı ekle, model, hafta, Top 100 ağırlığı veya çip seçimini değiştir; yeni sonucu yanına ekle. En fazla üç planı karşılaştırıp kendi tercihini işaretle."
          : "Pin a plan, change the model, horizon, Top 100 weight or chip, then pin the new result. Compare up to three plans and mark your own preference."}
      </p>
      <p>
        {tr
          ? "Tercihin FPL hesabında transfer yapmaz veya çip kullanmaz. Planlar ve notun yalnız bu tarayıcı sekmesinde tutulur; kadro veya veri görüntüsü değişirse sıfırlanır."
          : "Your preference does not make transfers or play chips in FPL. Plans and your note stay in this browser tab only and reset when the squad or data snapshot changes."}
      </p>
      <button
        type="button"
        className={styles.pin}
        disabled={!candidate || !!pinned || board.candidates.length >= 3}
        onClick={() =>
          candidate && change({ ...board, candidates: [...board.candidates, candidate] })
        }
      >
        {pinned
          ? tr
            ? "Bu plan eklendi"
            : "Plan pinned"
          : tr
            ? "Bu planı karşılaştırmaya ekle"
            : "Pin this plan"}
      </button>
      {!candidate && (
        <p role="note">
          {tr
            ? "Eklemek için mevcut seçimle ve bu kadronun verisiyle eşleşen, tamamlanmış bir plan gerekiyor."
            : "Pinning needs a completed plan matching these settings and this squad's data."}
        </p>
      )}
      {board.candidates.length === 3 && (
        <p>{tr ? "Yeni plan için önce birini kaldır." : "Remove a plan before adding another."}</p>
      )}
      <div className={styles.grid}>
        {board.candidates.map((c, i) => {
          const p = c.envelope.payload;
          const m = decisionMetrics(p);
          const label = String.fromCharCode(65 + i);
          const strategy =
            messages.leagueMembers.strategies[
              p.mode as keyof typeof messages.leagueMembers.strategies
            ]?.name ??
            {
              garantici: messages.decision.modes.safe,
              agresif: messages.decision.modes.aggressive,
              "asiri-agresif": messages.decision.modes.extreme,
            }[p.mode as "garantici" | "agresif" | "asiri-agresif"];
          return (
            <section className={styles.plan} key={c.id} aria-label={`Plan ${label}`}>
              <h3>Plan {label}</h3>
              <p>
                {p.prediction_model
                  ? tr
                    ? "Futbol · Deneysel"
                    : "Football · Experimental"
                  : tr
                    ? "Mevcut model"
                    : "Current model"}{" "}
                · {p.window} {tr ? "hafta" : "weeks"} · {strategy}
              </p>
              <p>
                {messages.leagueMembers.top100Weight(c.request.top100Weight ?? 0)} ·{" "}
                {tr ? "Hoca yorumu" : "Manager's word"}:{" "}
                {c.request.managersWord ? (tr ? "Açık" : "On") : tr ? "Kapalı" : "Off"} ·{" "}
                {tr ? "Çip tercihi" : "Chip preference"}: {chipName(c.request.chip)}
              </p>
              {c.request.rivalEntryId != null && (
                <p>
                  {tr ? "Rakip" : "Rival"}: #{c.request.rivalEntryId}
                </p>
              )}
              {c.request.preferences && (
                <p>
                  {tr ? "Tutulan oyuncu" : "Kept players"}:{" "}
                  {c.request.preferences.keep_players.length} ·{" "}
                  {tr ? "Alınmayacak oyuncu" : "Avoided players"}:{" "}
                  {c.request.preferences.avoid_players.length} · {tr ? "Hit yok" : "No hits"}:{" "}
                  {c.request.preferences.no_hits ? (tr ? "Evet" : "Yes") : tr ? "Hayır" : "No"} ·{" "}
                  {tr ? "Çipleri sakla" : "Save chips"}:{" "}
                  {c.request.preferences.save_chips ? (tr ? "Evet" : "Yes") : tr ? "Hayır" : "No"}
                </p>
              )}
              <dl className={styles.metrics}>
                <dt>{tr ? "İlk hafta net beklenen puan" : "First-week net expected points"}</dt>
                <dd>{number(m.net)}</dd>
                <dt>{tr ? "İlk hafta tutmaya göre net fark" : "First-week net gain over hold"}</dt>
                <dd>{number(m.gain)}</dd>
                <dt>{tr ? "Pencere net beklenen puanı" : "Horizon net expected points"}</dt>
                <dd>{number(m.horizonNet)}</dd>
                <dt>{tr ? "Pencere transfer cezası" : "Horizon transfer hits"}</dt>
                <dd>{m.horizonHits ?? "—"}</dd>
                <dt>{tr ? "Pencere sonunda serbest transfer" : "Free transfers at horizon end"}</dt>
                <dd>{m.remainingTransfers ?? "—"}</dd>
                <dt>{tr ? "İlk hafta kaptanı" : "First-week captain"}</dt>
                <dd>{p.captain?.name}</dd>
                <dt>{tr ? "İlk hafta çipi" : "First-week chip"}</dt>
                <dd>{chipName(p.chip)}</dd>
                <dt>{tr ? "Çözüm" : "Solver"}</dt>
                <dd>{p.solver_status}</dd>
                <dt>{tr ? "Amaç fonksiyonu sınır farkı" : "Objective bound gap"}</dt>
                <dd>{number(p.optimality_gap)}</dd>
              </dl>
              <p>
                {p.solver_status === "FEASIBLE"
                  ? tr
                    ? "Geçerli plan bulundu; en iyi çözüm olduğu kanıtlanmadı."
                    : "A feasible plan was found; optimality is not proved."
                  : tr
                    ? "Seçilen model ve kısıtlar altında optimum; gerçek puan garantisi değil."
                    : "Optimal under the selected model and constraints, not guaranteed actual points."}
              </p>
              {m.gain != null && m.gain < 0 && (
                <p role="note">
                  {tr
                    ? "Bu plan ilk hafta transfer yapmamaktan daha düşük net puan bekliyor; sonraki haftaların gerekçesini incele."
                    : "This plan expects fewer net points than holding this week; review the justification over later weeks."}
                </p>
              )}
              <p>
                {tr ? "İlk hafta transferleri" : "First-week transfers"}:{" "}
                {p.moves.length === 0
                  ? tr
                    ? "Transfer yok"
                    : "No transfers"
                  : p.moves
                      .map(
                        (move) =>
                          `${move.player_out?.name ?? "—"} → ${move.player_in?.name ?? "—"}`,
                      )
                      .join("; ")}
              </p>
              {!!p.stated_limits?.length && (
                <details>
                  <summary className={styles.summary}>
                    {tr ? "Planın varsayımları" : "Plan assumptions"}
                  </summary>
                  <ul>
                    {p.stated_limits.map((limit, j) => (
                      <li key={j}>{messages.leagueMembers.statedLimits[limit] ?? limit}</li>
                    ))}
                  </ul>
                </details>
              )}
              {c.envelope.source_kind === "example" && <p>{tr ? "Örnek veri" : "Example data"}</p>}
              <label>
                <input
                  type="radio"
                  name="decision-preference"
                  checked={board.preferred === c.id}
                  onChange={() => change({ ...board, preferred: c.id, note: "" })}
                />{" "}
                {tr ? `Tercihim: Plan ${label}` : `My preference: Plan ${label}`}
              </label>
              <div className={styles.actions}>
                <button type="button" onClick={() => setParams(decisionParams(params, c.request))}>
                  {tr ? "Ayarlarını aç" : "Open settings"}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    change({
                      ...board,
                      candidates: board.candidates.filter((v) => v.id !== c.id),
                      preferred: board.preferred === c.id ? null : board.preferred,
                      note: board.preferred === c.id ? "" : board.note,
                    })
                  }
                >
                  {tr ? "Kaldır" : "Remove"}
                </button>
              </div>
            </section>
          );
        })}
      </div>
      {board.preferred && (
        <label className={styles.note}>
          {tr ? "Bu planı neden tercih ettim?" : "Why do I prefer this plan?"}
          <textarea
            value={board.note}
            maxLength={500}
            onChange={(event) => change({ ...board, note: event.target.value })}
            placeholder={
              tr
                ? "Dakika güveni, gelecek fikstür, transfer hakkı, kaptan veya beklediğim haber…"
                : "Minutes security, upcoming fixtures, saved transfers, captaincy or news I am waiting for…"
            }
          />
        </label>
      )}
      {!stored && (
        <p role="status">
          {tr
            ? "Sekme kaydı kullanılamıyor. Seçim bu ekranda duruyor; yenileyince kaybolabilir."
            : "Tab storage is unavailable. Your choice remains on screen but may be lost on reload."}
        </p>
      )}
      <p>
        {tr
          ? "Net puan transfer cezası düşülmüş beklentidir. Farklı modellerin veya farklı uzunluktaki pencerelerin yüksek puanı, daha iyi plan olduğunu kanıtlamaz. Eksik ölçüm — ile gösterilir."
          : "Net points subtract transfer hits. Higher scores from different models or different horizons do not prove a better plan. Missing measurements are shown as —."}
      </p>
      <details>
        <summary className={styles.summary}>
          {tr ? "Karar vermeden önce" : "Before deciding"}
        </summary>
        <ul>
          <li>
            {tr
              ? "Oyuncunun beklenen dakikası ve sakatlık haberinin tarihi güvenilir mi?"
              : "Are expected minutes and the date of injury news reliable?"}
          </li>
          <li>
            {tr
              ? "Transfer önümüzdeki 3–5 haftada, kaptan seçenekleriyle birlikte değer katıyor mu?"
              : "Does the transfer add value across 3–5 weeks, including captain options?"}
          </li>
          <li>
            {tr
              ? "Puan cezası sonrası kazanç, transfer hakkını saklamaya değer mi?"
              : "Does the gain after hits justify spending a free transfer?"}
          </li>
          <li>
            {tr
              ? "Çipi şimdi harcamak yerine sonraki fırsata saklamak mantıklı mı?"
              : "Should the chip be saved for another opportunity?"}
          </li>
          <li>
            {tr
              ? "Kararı değiştirecek hangi hoca haberi veya ilk 11 bilgisi eksik?"
              : "Which manager update or lineup news could change this decision?"}
          </li>
        </ul>
        <p>
          {tr
            ? "Bu sorular karar çerçevesidir; başarı garantisi veya test edilmiş yeni bir tahmin modeli değildir."
            : "These questions frame the decision; they are not a guarantee of success or a validated new prediction model."}
        </p>
        <a href="https://www.premierleague.com/en/news/4322002">
          {tr ? "FPL uzmanlarının değerlendirmeleri" : "FPL experts' lessons"}
        </a>
      </details>
    </Card>
  );
}
