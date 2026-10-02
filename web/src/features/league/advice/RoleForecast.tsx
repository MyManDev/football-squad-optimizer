import { useLanguage } from "../../../i18n/context";
import { points, utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "İlk 11 ve süre beklentisi",
    start: "İlk 11",
    cameo: "Sonradan girer",
    zero: "Oynamaz",
    minutes: "Beklenen dakika",
    sixty: "60 dakikaya ulaşır",
    unknown: "İlk 11 bilgisi için yeterli kayıt yok",
    fixture: "Maç",
    detail:
      "Bunlar geçmiş maçlardan öğrenilmiş model tahminleridir; FPL yüzdesi ilk 11 garantisi değildir. FPL oynayabilirliği bir kez uygulanır. Bağımsız doğruluk ölçümü henüz tamamlanmış değildir.",
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
      "Bu, oyuncunun yalnızca bu maç için model tahminidir; kaptan çarpanı ve Top100 seçim ağırlığı öncesidir. Oynayabilirlik zaten bir kez uygulanmıştır. Diğer katkılar belirli bir olayın garantisi değildir; negatif olabilir. Alt sınır düzeltmesi, negatif toplamı sıfıra getirir.",
  },
  en: {
    title: "Starting role and expected minutes",
    start: "Starts",
    cameo: "Comes on",
    zero: "Does not play",
    minutes: "Expected minutes",
    sixty: "Reaches 60 minutes",
    unknown: "Insufficient recorded starting-role evidence",
    fixture: "Fixture",
    detail:
      "These are model estimates learned from past matches. The FPL percentage is not a guaranteed start. Captured eligibility is applied once. Independent accuracy validation is not complete.",
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
      "This is the player's model estimate for this fixture only, before captain multipliers and Top100 selection weighting. Eligibility is already applied once. Other contributions do not guarantee any particular event and may be negative. The floor adjustment brings a negative total to zero.",
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
  const percent = (value: number | null) =>
    value === null ? "—" : `${points(value * 100, 0, locale)}%`;
  return (
    <details className={styles.adviceSection} data-testid="role-forecast">
      <summary>{copy.title}</summary>
      <p className={styles.honesty}>{copy.detail}</p>
      <ul className={styles.assumptionList}>
        {data.rows.map((row) => (
          <li key={`${row.player_id}-${row.fixture_id}`}>
            <strong>{row.name}</strong> · {utcShort(row.kickoff, locale)}
            <p>
              {copy.start}: {percent(row.start_probability)} · {copy.cameo}:{" "}
              {percent(row.cameo_probability)} · {copy.zero}: {percent(row.zero_probability)}
            </p>
            <p>
              {copy.minutes}: {points(row.expected_minutes, 1, locale)} · {copy.sixty}:{" "}
              {percent(row.sixty_minute_probability)}
            </p>
            {row.start_probability === null && <p className={styles.muted}>{copy.unknown}</p>}
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
