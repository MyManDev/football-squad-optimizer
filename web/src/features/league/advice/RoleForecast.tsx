import { useLanguage } from "../../../i18n/context";
import { points, utcShort } from "../../../lib/format";
import type { AdviceRolePointComponents, EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "İlk 11 ve süre beklentisi",
    minutes: "Beklenen dakika",
    pointsTitle: "Bu maç için beklenen puanın ayrıntısı",
    pointTerms: {
      appearance: "Süre puanı",
      goals: "Gol",
      assists: "Asist",
      clean_sheet: "Gol yememe",
      defcon: "Savunma katkısı",
      other: "Diğer katkılar",
    },
    total: "Toplam oyuncu puanı",
  },
  en: {
    title: "Starting role and expected minutes",
    minutes: "Expected minutes",
    pointsTitle: "Expected points for this fixture",
    pointTerms: {
      appearance: "Appearance points",
      goals: "Goals",
      assists: "Assists",
      clean_sheet: "Clean sheet",
      defcon: "Defensive contributions",
      other: "Other contributions",
    },
    total: "Total player points",
  },
};

const POINT_TERMS = ["appearance", "goals", "assists", "clean_sheet", "defcon", "other"] as const;

/** A term as the page prints it: the floor at zero counts under "other", so the rows add up. */
function printedTerm(terms: AdviceRolePointComponents, key: (typeof POINT_TERMS)[number]): number {
  return key === "other" ? terms.other + terms.clipping : terms[key];
}

export function RoleForecast({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const data = view.role_forecast;
  if (!data?.rows.length) return null;
  const copy = COPY[language];
  return (
    <details className={styles.adviceSection} data-testid="role-forecast">
      <summary>{copy.title}</summary>
      <ul className={styles.assumptionList}>
        {data.rows.map((row) => (
          <li key={`${row.player_id}-${row.fixture_id}`}>
            <strong>{row.name}</strong> · {utcShort(row.kickoff, locale)}
            <p>
              {copy.minutes}: {points(row.expected_minutes, 1, locale)}
            </p>
            {row.point_components && (
              <details data-testid="role-point-components">
                <summary>{copy.pointsTitle}</summary>
                <ul className={styles.assumptionList}>
                  {POINT_TERMS.map((key) => (
                    <li key={key}>
                      {copy.pointTerms[key]}:{" "}
                      <span className="num">
                        {points(printedTerm(row.point_components!, key), 2, locale)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p>
                  <strong>
                    {copy.total}:{" "}
                    <span className="num">{points(row.point_components.total, 2, locale)}</span>
                  </strong>
                </p>
              </details>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
