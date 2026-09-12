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
      "- means not measured. Minutes shortfall covers starters who played; negative means more minutes than projected. Captain shortfall is expected minus received bonus points.",
    legacy: "Named eleven; autosubs and vice-captain recovery unavailable",
    synthetic: "Reconstructed legal squad within the opening budget; no transfer history",
    game: "Game's published average",
    official: "Official substitutions and captain scoring",
    absent: "Decision record unavailable",
    pending: "Awaiting settled results",
    names: {
      system: "System",
      base: "Bare component",
      elite_xi: "Lagged elite XI",
      ownership_template: "Ownership template",
      league_mean: "League mean, net",
      game_mean: "Game average",
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
      "- ölçülmedi demektir. Dakika açığı oynayan ilk 11 oyuncularını kapsar; negatif değer tahminden fazla dakika oynandığını gösterir. Kaptan açığı, beklenen ile gerçekleşen ek puan farkıdır.",
    legacy: "Adı konan ilk 11; otomatik değişiklik ve ikinci kaptan getirisi bilinmiyor",
    synthetic: "Açılış bütçesiyle kurallara uygun yeniden kurulan kadro; transfer geçmişi yok",
    game: "Oyunun yayımladığı ortalama",
    official: "Resmi değişiklik ve kaptan puanlaması",
    absent: "Karar kaydı yok",
    pending: "Yerleşmiş sonuç bekleniyor",
    names: {
      system: "Sistem",
      base: "Çıplak bileşen",
      elite_xi: "Önceki haftanın elit XI'i",
      ownership_template: "Sahiplik şablonu",
      league_mean: "Lig ortalaması, net",
      game_mean: "Oyun ortalaması",
    },
  },
};

export function ScoreboardComparisons({ weeks }: { weeks: ScoreboardGameweek[] }) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  if (!weeks.some((week) => Array.isArray(week.comparisons) && week.comparisons.length))
    return null;
  const number = (value: number | null | undefined) =>
    value == null || !Number.isFinite(value) ? "-" : points(value, 1, locale);
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
              (Array.isArray(week.comparisons) ? week.comparisons : []).map((row) => {
                const settled = week.finished === true && week.data_checked === true;
                const errors = settled ? row.diagnostics : undefined;
                return (
                  <tr key={`${week.gameweek}-${row.kind}`}>
                    <td>{week.gameweek}</td>
                    <th scope="row">
                      {copy.names[row.kind]}
                      {!settled && <div className={styles.sub}>{copy.pending}</div>}
                      {settled && row.net == null && week.ours == null && row.kind === "system" && (
                        <div className={styles.sub}>{copy.absent}</div>
                      )}
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
                    <td>
                      {errors?.zero_minute_starters != null &&
                      Number.isInteger(errors.zero_minute_starters)
                        ? points(errors.zero_minute_starters, 0, locale)
                        : "-"}
                    </td>
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
    </section>
  );
}
