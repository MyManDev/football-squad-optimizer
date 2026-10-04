import { useLanguage } from "../../../i18n/context";
import { points, utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "İlk 11 ve süre beklentisi",
    minutes: "Beklenen dakika",
    unknown: "İlk 11 bilgisi için yeterli kayıt yok",
    detail:
      "Bu süre tahmini geçmiş maçlardaki ilk 11, sonradan oyuna girme ve oynamama kayıtlarını kullanır.",
    updated: "Kaynaklı oynama veya süre bilgisi uygulandı.",
    pointsTitle: "Bu maç için beklenen puanın ayrıntısı",
    pointTerms: {
      appearance: "Süre puanı",
      goals: "Gol",
      assists: "Asist",
      clean_sheet: "Gol yememe",
      defcon: "Savunma katkısı",
      other: "Diğer katkılar (modelin kalan tahmini)",
      clipping: "Sıfır alt sınırı düzeltmesi",
    },
    total: "Toplam oyuncu puanı",
    pointLimit:
      "Kaptan çarpanı ve Top100 ağırlığı öncesidir. Alt sınır düzeltmesi, negatif toplamı sıfıra getirir.",
  },
  en: {
    title: "Starting role and expected minutes",
    minutes: "Expected minutes",
    unknown: "Insufficient recorded starting-role evidence",
    detail:
      "This minutes estimate uses past records of starts, substitute appearances and not playing.",
    updated: "A sourced availability or minutes statement was applied.",
    pointsTitle: "Expected points for this fixture",
    pointTerms: {
      appearance: "Appearance points",
      goals: "Goals",
      assists: "Assists",
      clean_sheet: "Clean sheet",
      defcon: "Defensive contributions",
      other: "Other contributions (remaining model estimate)",
      clipping: "Zero-floor adjustment",
    },
    total: "Total player points",
    pointLimit:
      "Before the captain multiplier and the Top100 weight. The floor adjustment brings a negative total to zero.",
  },
};

const POINT_TERMS = [
  "appearance",
  "goals",
  "assists",
  "clean_sheet",
  "defcon",
  "other",
  "clipping",
] as const;

export function RoleForecast({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const data = view.role_forecast;
  if (!data?.rows.length) return null;
  const copy = COPY[language];
  return (
    <details className={styles.adviceSection} data-testid="role-forecast">
      <summary>{copy.title}</summary>
      <p className={styles.honesty}>{copy.detail}</p>
      <ul className={styles.assumptionList}>
        {data.rows.map((row) => (
          <li key={`${row.player_id}-${row.fixture_id}`}>
            <strong>{row.name}</strong> · {utcShort(row.kickoff, locale)}
            <p>
              {copy.minutes}: {points(row.expected_minutes, 1, locale)}
            </p>
            {row.status === "unavailable_no_known_start_labels" && (
              <p className={styles.muted}>{copy.unknown}</p>
            )}
            {row.news_applied && <p className={styles.muted}>{copy.updated}</p>}
            {row.point_components && (
              <details data-testid="role-point-components">
                <summary>{copy.pointsTitle}</summary>
                <ul className={styles.assumptionList}>
                  {POINT_TERMS.map((key) => (
                    <li key={key}>
                      {copy.pointTerms[key]}:{" "}
                      <span className="num">{points(row.point_components![key], 2, locale)}</span>
                    </li>
                  ))}
                </ul>
                <p>
                  <strong>
                    {copy.total}:{" "}
                    <span className="num">{points(row.point_components.total, 2, locale)}</span>
                  </strong>
                </p>
                <p className={styles.honesty}>{copy.pointLimit}</p>
              </details>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
