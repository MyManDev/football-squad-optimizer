import { useLanguage } from "../../../i18n/context";
import { signedPoints } from "../../../lib/format";
import type { MemberChipRecommendations } from "../types";
import styles from "./ChipRecommendations.module.css";

const COPY = {
  en: {
    title: "Chip calendar",
    hold: "Hold",
    play: (week: number) => `Play in GW${week}`,
    gain: (value: string) => `expected ${value} points`,
    last: (week: number) => `Last use: GW${week} deadline`,
    opens: (week: number) => `Available from GW${week}`,
    outside: "outside this window",
    noGain: "no additional chip gain found",
    unproven: "Found plan; best plan not yet proved",
    scope: (weeks: string) =>
      `Prices cover ${weeks} against the no-chip plan. Each chip is compared independently; only one can be played per week. Holding value beyond this window is not priced.`,
    names: {
      bboost: "Bench Boost",
      "3xc": "Triple Captain",
      wildcard: "Wildcard",
      freehit: "Free Hit",
    },
  },
  tr: {
    title: "Chip takvimi",
    hold: "Tut",
    play: (week: number) => `GW${week}'de oyna`,
    gain: (value: string) => `beklenen ${value} puan`,
    last: (week: number) => `Son kullanım: GW${week} kadro son tarihi`,
    opens: (week: number) => `GW${week}'den itibaren kullanılabilir`,
    outside: "bu pencerenin dışında",
    noGain: "chip için ek kazanç bulunmadı",
    unproven: "Bulunan plan; en iyi plan olduğu henüz doğrulanmadı",
    scope: (weeks: string) =>
      `Fiyatlar ${weeks} toplamını chipsiz planla karşılaştırır. Her chip ayrı değerlendirilir; aynı haftada yalnız biri oynanabilir. Pencere sonrasındaki saklama değeri hesaplanmadı.`,
    names: {
      bboost: "Bench Boost",
      "3xc": "Üçlü Kaptan",
      wildcard: "Wildcard",
      freehit: "Free Hit",
    },
  },
};

export function ChipRecommendations({ value }: { value?: MemberChipRecommendations }) {
  const { language, locale } = useLanguage();
  if (!value?.comparisons.length) return null;
  const copy = COPY[language];
  const weeks = value.gameweeks.map((week) => `GW${week}`).join(" · ");
  return (
    <section className={styles.section} aria-label={copy.title}>
      <h3>{copy.title}</h3>
      <p>{copy.scope(weeks)}</p>
      <ul className={styles.list}>
        {value.comparisons.map((row) => (
          <li key={`${row.chip}-${row.available_from_gameweek}`}>
            <strong>{copy.names[row.chip]}</strong>
            <span>
              {row.action === "play" && row.gameweek !== null ? copy.play(row.gameweek) : copy.hold}
              {row.expected_points_gain !== null
                ? ` · ${copy.gain(signedPoints(row.expected_points_gain, 1, locale))}`
                : ` · ${row.reason === "outside_horizon" ? copy.outside : copy.noGain}`}
            </span>
            <small>
              {copy.opens(row.available_from_gameweek)} · {copy.last(row.last_usable_gameweek)}
            </small>
            {row.solver_status !== null &&
              (row.solver_status !== "OPTIMAL" || value.control_solver_status !== "OPTIMAL") && (
                <small>{copy.unproven}</small>
              )}
          </li>
        ))}
      </ul>
    </section>
  );
}
