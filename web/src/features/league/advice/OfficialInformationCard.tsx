import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import type { DecisionInformation } from "./informationFacts";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "FPL bilgileri ve bu plan",
    sourceDate: "Haberin tarihi",
    sourceValue: "FPL oynama değeri",
    status: {
      a: "Uygun",
      d: "Şüpheli",
      i: "Sakat",
      s: "Cezalı",
      u: "Kullanılamıyor",
      n: "Kadro dışı",
    },
    noFlags: "Bu plandaki oyuncular için gösterilecek FPL uyarısı yok.",
    changed: "Yeni bilgilerle hesaplamak için Hesapla düğmesini kullanabilirsin.",
  },
  en: {
    title: "FPL information and this plan",
    sourceDate: "News date",
    sourceValue: "FPL playing value",
    status: {
      a: "Available",
      d: "Doubtful",
      i: "Injured",
      s: "Suspended",
      u: "Unavailable",
      n: "Not in squad",
    },
    noFlags: "No FPL alerts to show for the players in this plan.",
    changed: "Use Compute to request a result with the new information.",
  },
};

export function NewInformationNotice({
  view,
  latest,
}: {
  view: EntryAdvice;
  latest?: DecisionInformation;
}) {
  const { language } = useLanguage();
  if (
    view.prediction_model?.id !== "football" ||
    !latest ||
    latest.source_snapshot_id !== view.source_snapshot_id ||
    latest.revision === view.decision_information?.revision
  )
    return null;
  return (
    <p role="status" className={styles.honesty} data-testid="new-information-notice">
      {COPY[language].changed}
    </p>
  );
}

/**
 * The central league injury source is disabled in production (the producer's
 * ``OFFICIAL_INJURY_SOURCE_ENABLED`` is False, with no override). The page mirrors that:
 * a payload's `official_injuries` is validated and never drawn, whoever built it.
 */
export function OfficialInformationCard({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const feed = view.official_information;
  if (!feed) return null;
  const copy = COPY[language];
  const flagged = feed.players.filter(
    (p) =>
      p.status !== "a" ||
      (p.source_chance_percent !== null && p.source_chance_percent !== 100) ||
      p.news_state === "present",
  );
  return (
    <details className={styles.adviceSection} data-testid="official-information">
      <summary>{copy.title}</summary>
      {flagged.length === 0 ? (
        <p>{copy.noFlags}</p>
      ) : (
        <ul className={styles.assumptionList}>
          {flagged.map((p) => (
            <li key={p.player_id}>
              <strong>{p.name}</strong> · {p.team_name}
              {Object.hasOwn(copy.status, p.status)
                ? ` · ${copy.status[p.status as keyof typeof copy.status]}`
                : null}
              {p.source_chance_percent === null ? null : (
                <p>{String(copy.sourceValue + ": " + p.source_chance_percent + "/100")}</p>
              )}
              {p.source_added_at ? (
                <p>
                  {copy.sourceDate}:{" "}
                  <time dateTime={p.source_added_at}>{utcShort(p.source_added_at, locale)}</time>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
