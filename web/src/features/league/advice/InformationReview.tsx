import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";
import { WeekLineup } from "./WeekLineup";

const COPY = {
  tr: {
    title: "Haber gelince plan nasıl değişir?",
    playingValue: "FPL oynama değeri",
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
    starters: "İlk 11",
    firstWeek: "İlk haftanın on biri",
    captain: "Kaptan",
    vice: "Yardımcı kaptan",
    bench: "Yedek sırası",
    resources: "Bu ilk hamleden sonra",
  },
  en: {
    title: "How could news change the plan?",
    playingValue: "FPL playing value",
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
    starters: "Starting eleven",
    firstWeek: "First week's eleven",
    captain: "Captain",
    vice: "Vice-captain",
    bench: "Bench order",
    resources: "After this first action",
  },
};

export function InformationReview({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const copy = COPY[language];
  const review = view.information_review;
  if (
    !review ||
    review.version !== "football_information_review_v1" ||
    review.status !== "compared"
  )
    return null;
  const net = (value: number | null) =>
    value !== null && Number.isFinite(value) ? points(value, 1, locale) : "—";
  return (
    <section
      className={styles.adviceSection}
      aria-label={copy.title}
      data-testid="information-review"
    >
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
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
            {copy.expected}: <strong className="num">{net(candidate.expected_net_points)}</strong>
          </p>
          {review.comparison?.candidates
            .filter((row) => row.index === index)
            .map((row) => (
              <p key={row.index} data-testid="policy-comparison">
                {copy.resources}: {row.first_state.free_transfers} {copy.ft} · {copy.bank}:{" "}
                {points(row.first_state.bank_tenths / 10, 1, locale)}
              </p>
            ))}
          {candidate.branches.map((branch) => (
            <details key={branch.state}>
              <summary>{branch.state === "eligible" ? copy.eligible : copy.unavailable}</summary>
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
                    {week.lineup && <WeekLineup gameweek={week.gameweek} lineup={week.lineup} />}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </details>
      ))}
    </section>
  );
}
