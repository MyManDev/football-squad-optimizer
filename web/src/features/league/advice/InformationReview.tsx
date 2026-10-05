import { useLanguage } from "../../../i18n/context";
import { points, utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";
import { WeekLineup } from "./WeekLineup";

const COPY = {
  tr: {
    title: "Haber gelince plan nasıl değişir?",
    playingValue: "FPL oynama değeri",
    source: "Bilginin kaydedildiği an",
    selected: "Seçilen ilk hamle",
    alternative: "Diğer ilk hamle",
    baseline: "Başlangıç planı",
    hold: "Bu hafta transfer yapma",
    eligible: "Oynayabilir bilgisi gelirse",
    unavailable: "Oynayamaz bilgisi gelirse",
    expected: "Pencere beklenen net puanı",
    hits: "Pencere transfer cezası",
    conditional: "Koşula bağlı sonraki hamleler",
    keep: "Transfer yok",
    ft: "ücretsiz transfer sonraki haftaya",
    bank: "banka",
    next: "Sonraki karar haftası",
    scale: "Puanlar temel futbol tahmininden gelir.",
    expectedScale:
      "Puanlar temel futbol tahmininden gelir; otomatik değişiklikler ve kaptan oynamazsa yardımcı kaptanın ek puanı dahildir.",
    starters: "İlk 11",
    firstWeek: "İlk haftanın on biri",
    captain: "Kaptan",
    vice: "Yardımcı kaptan",
    bench: "Yedek sırası",
    range: "Hesaplanan haber senaryolarındaki puan aralığı",
    gap: "Başlangıç planına göre senaryo farkı",
    resources: "Bu ilk hamleden sonra",
    dominates: "Karşılaştırılan tüm haber senaryolarında başlangıç planından geri kalmıyor.",
    fallback: "Bu karşılaştırma tamamlanamadı. Tam ve geçerli başlangıç planı korunuyor.",
    single:
      "Farklı ve geçerli bir ilk hamle bulunamadı. Farklı bir ilk hamle karşılaştırması yapılmadı; başlangıç planı korunuyor.",
    missing:
      "Bu kadro için karşılaştırmaya uygun, sayısal oynama belirsizliği bulunmadı. Mevcut planlama yöntemi kullanılıyor.",
    components:
      "Bu tahmin dosyasında koşullu takım ve maç bileşenleri bulunmuyor. Toplam puanlardan sakatlık senaryosu çıkarılmadı; mevcut planlama yöntemi kullanılıyor.",
  },
  en: {
    title: "How could news change the plan?",
    playingValue: "FPL playing value",
    source: "Information captured at",
    selected: "Selected first action",
    alternative: "Other first action",
    baseline: "Baseline plan",
    hold: "Make no transfer this week",
    eligible: "If eligibility is confirmed",
    unavailable: "If unavailability is confirmed",
    expected: "Expected window net points",
    hits: "Window transfer hits",
    conditional: "Conditional later moves",
    keep: "No transfer",
    ft: "free transfers carried forward",
    bank: "bank",
    next: "Next decision gameweek",
    scale: "Points use the base football forecast.",
    expectedScale:
      "Points use the base football forecast, including automatic substitutions and the vice-captain bonus when the captain does not play.",
    starters: "Starting eleven",
    firstWeek: "First week's eleven",
    captain: "Captain",
    vice: "Vice-captain",
    bench: "Bench order",
    range: "Point range across the computed news scenarios",
    gap: "Scenario difference from the baseline",
    resources: "After this first action",
    dominates: "No worse than the baseline in every compared news scenario.",
    fallback: "This comparison could not be completed. The complete feasible baseline is retained.",
    single:
      "No distinct feasible first action was found. No distinct first-action comparison was made; the baseline plan is retained.",
    missing:
      "No usable quantified playing uncertainty was found for this squad. The existing planner is used.",
    components:
      "This forecast file lacks conditional team and match components. Injury scenarios were not inferred from total points; the existing planner is used.",
  },
};

export function InformationReview({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = COPY[language];
  const review = view.information_review;
  if (!review || review.version !== "football_information_review_v1") return null;
  const net = (value: number | null) =>
    value !== null && Number.isFinite(value) ? points(value, 1, locale) : "—";
  return (
    <section
      className={styles.adviceSection}
      aria-label={copy.title}
      data-testid="information-review"
    >
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      {review.status === "compared" ? (
        <>
          <p>
            <strong>{review.player_name}</strong>
            {typeof review.source_playing_chance_percent === "number" ? (
              <>
                {" "}
                · {copy.playingValue}: {review.source_playing_chance_percent}/100
              </>
            ) : null}
          </p>
          <p className={styles.muted}>
            {copy.next}: {review.information_gameweek}
          </p>
          <p className={styles.muted}>
            {view.lineup_expectation ? copy.expectedScale : copy.scale}
          </p>
          {review.candidates.map((candidate, index) => (
            <details key={index} open={candidate.selected}>
              <summary>
                {candidate.selected ? copy.selected : copy.alternative}
                {candidate.baseline ? ` · ${copy.baseline}` : ""}
              </summary>
              <p>
                {candidate.transfers_in.length
                  ? `${candidate.transfers_out.join(", ")} → ${candidate.transfers_in.join(", ")}`
                  : copy.hold}
              </p>
              {candidate.chip && (
                <p>{messages.leagueMembers.chipNames[candidate.chip] ?? candidate.chip}</p>
              )}
              {candidate.first_lineup && (
                <div className={styles.muted}>
                  {/* The eleven of the decision week, named as that week so a later branch's
                      squad is not read as the first decision. */}
                  <p>
                    {copy.firstWeek}: {messages.common.gameweekShort(view.gameweek)}
                  </p>
                  <p>
                    {copy.captain}: {candidate.first_lineup.captain} · {copy.vice}:{" "}
                    {candidate.first_lineup.vice_captain}
                  </p>
                  <p>
                    {copy.starters}: {candidate.first_lineup.starting_xi.join(", ")}
                  </p>
                  <p>
                    {copy.bench}: {candidate.first_lineup.bench.join(" → ")}
                  </p>
                </div>
              )}
              <p>
                {copy.expected}:{" "}
                <strong className="num">{net(candidate.expected_net_points)}</strong>
              </p>
              {review.comparison?.candidates
                .filter((row) => row.index === index)
                .map((row) => (
                  <div key={row.index} data-testid="policy-comparison">
                    <p>
                      {copy.range}:{" "}
                      <strong className="num">
                        {net(row.scenario_min)} – {net(row.scenario_max)}
                      </strong>
                    </p>
                    <p>
                      {copy.gap}: {net(row.minimum_gap_vs_baseline)} –{" "}
                      {net(row.maximum_gap_vs_baseline)}
                    </p>
                    <p>
                      {copy.resources}: {row.first_state.free_transfers} {copy.ft} · {copy.bank}:{" "}
                      {points(row.first_state.bank_tenths / 10, 1, locale)}
                    </p>
                    {row.dominates_baseline && <p>{copy.dominates}</p>}
                  </div>
                ))}
              {candidate.branches.map((branch) => (
                <details key={branch.state}>
                  <summary>
                    {branch.state === "eligible" ? copy.eligible : copy.unavailable}
                  </summary>
                  <p>
                    {copy.expected}: {net(branch.expected_net_points)} · {copy.hits}:{" "}
                    {net(branch.hit_points)}
                  </p>
                  <p className={styles.muted}>{copy.conditional}</p>
                  <ul>
                    {branch.weeks.map((week) => (
                      <li key={week.gameweek}>
                        {messages.common.gameweekShort(week.gameweek)}:{" "}
                        {week.transfers_in.length
                          ? `${week.transfers_out.join(", ")} → ${week.transfers_in.join(", ")}`
                          : copy.keep}
                        {week.chip
                          ? ` · ${messages.leagueMembers.chipNames[week.chip] ?? week.chip}`
                          : ""}
                        {` · ${week.free_transfers} ${copy.ft} · ${copy.bank}: ${points(week.bank_tenths / 10, 1, locale)}`}
                        {week.lineup && (
                          <WeekLineup gameweek={week.gameweek} lineup={week.lineup} />
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              ))}
            </details>
          ))}
        </>
      ) : (
        <p className={styles.muted}>
          {review.reason.startsWith("incomplete_")
            ? copy.fallback
            : review.reason === "no_distinct_alternative"
              ? copy.single
              : review.reason === "conditional_team_components_unavailable"
                ? copy.components
                : copy.missing}
        </p>
      )}
      <p className={styles.muted}>
        {copy.source}: {utcShort(review.captured_at_utc, locale)}
      </p>
    </section>
  );
}
