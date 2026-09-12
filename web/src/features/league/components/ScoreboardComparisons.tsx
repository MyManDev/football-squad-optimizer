import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { ScoreboardGameweek } from "../types";
import styles from "./ScoreboardCard.module.css";

const COPY = {
  en: {
    title: "Weekly comparison and error breakdown",
    week: "GW",
    name: "Decision",
    net: "Points",
    zero: "Starters with no minutes",
    minutes: "Minutes shortfall",
    captain: "Captain shortfall",
    autosub: "Autosub recovery",
    missing:
      "— means not measured. Minutes shortfall covers starters who played; negative means more minutes than projected. Captain shortfall is expected minus received bonus points.",
    legacy: "Named eleven; autosubs and vice-captain recovery unavailable",
    synthetic: "Reconstructed legal squad within the opening budget; no transfer history",
    game: "Game's published average",
    official: "Official substitutions and captain scoring",
    absent: "Decision record unavailable",
    pending: "Awaiting settled results",
    chipHistory: "Recorded chip alternatives",
    chipBasis:
      "The price covers the whole window; realized points cover only the chip week. These are recorded alternatives, not evidence that a member played them.",
    member: "Member",
    window: "Window",
    chipWeek: "Chip week",
    price: "Expected gain",
    realized: "Realized chip-week points",
    hold: "Hold",
    names: {
      system: "System",
      base: "Bare component",
      elite_xi: "Lagged elite XI",
      ownership_template: "Ownership template",
      league_mean: "League mean, net",
      game_mean: "Game average",
      member_advice: "Member advice",
    },
  },
  tr: {
    title: "Haftalık karşılaştırma ve hata ayrıştırması",
    week: "GW",
    name: "Karar",
    net: "Puan",
    zero: "Sıfır dakikalı ilk 11",
    minutes: "Dakika açığı",
    captain: "Kaptan açığı",
    autosub: "Otomatik değişiklik getirisi",
    missing:
      "— ölçülmedi demektir. Dakika açığı oynayan ilk 11 oyuncularını kapsar; negatif değer tahminden fazla dakika oynandığını gösterir. Kaptan açığı, beklenen ile gerçekleşen ek puan farkıdır.",
    legacy: "Adı konan ilk 11; otomatik değişiklik ve ikinci kaptan getirisi bilinmiyor",
    synthetic: "Açılış bütçesiyle kurallara uygun yeniden kurulan kadro; transfer geçmişi yok",
    game: "Oyunun yayımladığı ortalama",
    official: "Resmi değişiklik ve kaptan puanlaması",
    absent: "Karar kaydı yok",
    pending: "Yerleşmiş sonuç bekleniyor",
    chipHistory: "Kayıtlı chip seçenekleri",
    chipBasis:
      "Fiyat pencerenin tamamını, gerçekleşen puan yalnız chip haftasını kapsar. Bunlar kayıtlı seçeneklerdir; üyenin uyguladığı anlamına gelmez.",
    member: "Üye",
    window: "Pencere",
    chipWeek: "Chip haftası",
    price: "Beklenen ek puan",
    realized: "Gerçekleşen chip haftası puanı",
    hold: "Tut",
    names: {
      system: "Sistem",
      base: "Çıplak bileşen",
      elite_xi: "Önceki haftanın elit XI'i",
      ownership_template: "Sahiplik şablonu",
      league_mean: "Lig ortalaması, net",
      game_mean: "Oyun ortalaması",
      member_advice: "Üye tavsiyesi",
    },
  },
};

export function ScoreboardComparisons({ weeks }: { weeks: ScoreboardGameweek[] }) {
  const { language, locale, messages } = useLanguage();
  const copy = COPY[language];
  if (!weeks.some((week) => week.comparisons?.length)) return null;
  const number = (value: number | null | undefined) =>
    value == null ? "—" : points(value, 1, locale);
  return (
    <section aria-label={copy.title}>
      <h3>{copy.title}</h3>
      <p className={styles.notice}>{copy.missing}</p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className="visually-hidden">{copy.title}</caption>
          <thead>
            <tr>
              {[
                copy.week,
                copy.name,
                copy.net,
                copy.zero,
                copy.minutes,
                copy.captain,
                copy.autosub,
              ].map((label) => (
                <th key={label} scope="col">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weeks.flatMap((week) =>
              (week.comparisons ?? []).map((row) => {
                const settled = week.finished && week.data_checked;
                const errors = settled ? row.diagnostics : undefined;
                return (
                  <tr key={`${week.gameweek}-${row.kind}-${row.entry_id ?? ""}`}>
                    <td>{week.gameweek}</td>
                    <th scope="row">
                      {copy.names[row.kind]}
                      {row.entry_id != null && ` · ${row.entry_id}`}
                      {!settled && <div className={styles.sub}>{copy.pending}</div>}
                      {settled &&
                        week.decision_record_status === "missing" &&
                        row.kind === "system" && <div className={styles.sub}>{copy.absent}</div>}
                      {settled && row.net !== null && (
                        <div className={styles.sub}>
                          {row.kind === "game_mean"
                            ? copy.game
                            : row.kind === "elite_xi" || row.kind === "ownership_template"
                              ? copy.synthetic
                              : row.scoring_basis === "named_eleven_no_autosubs"
                                ? copy.legacy
                                : row.scoring_basis === "official_autosub_captain_v2"
                                  ? copy.official
                                  : null}
                        </div>
                      )}
                    </th>
                    <td>{number(settled ? row.net : null)}</td>
                    <td>{number(errors?.zero_minute_starters)}</td>
                    <td>{number(errors?.minutes_shortfall)}</td>
                    <td>{number(errors?.captain_shortfall)}</td>
                    <td>{number(errors?.autosub_recovery)}</td>
                  </tr>
                );
              }),
            )}
          </tbody>
        </table>
      </div>
      {weeks
        .filter((week) => week.chip_recommendations?.length)
        .map((week) => (
          <details key={week.gameweek}>
            <summary>
              {copy.chipHistory} · GW{week.gameweek}
            </summary>
            <p className={styles.notice}>{copy.chipBasis}</p>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    {[
                      copy.member,
                      "Chip",
                      copy.window,
                      copy.chipWeek,
                      copy.price,
                      copy.realized,
                    ].map((label) => (
                      <th key={label} scope="col">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {week.chip_recommendations!.map((row) => (
                    <tr
                      key={`${row.entry_id}-${row.window}-${row.chip}-${row.available_from_gameweek}`}
                    >
                      <td>{row.entry_id}</td>
                      <th scope="row">{messages.leagueMembers.chipNames[row.chip]}</th>
                      <td>{row.window}</td>
                      <td>{row.gameweek === null ? copy.hold : `GW${row.gameweek}`}</td>
                      <td>{number(row.expected_points_gain)}</td>
                      <td>{number(row.realized_chip_week_net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))}
    </section>
  );
}
