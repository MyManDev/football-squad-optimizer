import { StatementOutcomes } from "./StatementOutcomes";
import { RoleForecast } from "./RoleForecast";
import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Oynama haberleri nasıl kullanıldı?",
    checked: "Kontrol edilen FPL oynayabilirlik kaydı",
    statements: "Değerlendirilen hoca açıklaması",
    asOf: "Bilgi kesiti",
    dateUnknown: "Tarih bildirilmedi",
    gameweekUnknown: "Hafta bildirilmedi",
    noneApplied: "Bu tahmine uygulanmış hoca açıklaması yok.",
    noStatements: "Bu hafta değerlendirilecek hoca açıklaması okunmadı.",
    allRejected: "Okunan açıklamaların hiçbiri gerekli koşulları sağlamadı; tahmin değişmedi.",
    applied: "Doğrulanmış haberin uygulandığı oyuncu",
    unapplied: "Uygulanamayan açıklama",
    explanation: "FPL oynayabilirlik kayıtları ile hoca açıklaması ayrı değerlendirilir.",
  },
  en: {
    title: "How was playing news used?",
    checked: "FPL availability records checked",
    statements: "Coach statements considered",
    asOf: "Information as of",
    dateUnknown: "Date not reported",
    gameweekUnknown: "Gameweek not reported",
    noneApplied: "No coach statement was applied to this forecast.",
    noStatements: "No coach statement was read for this week.",
    allRejected: "None of the statements read met the requirements; the forecast is unchanged.",
    applied: "Players with verified statements applied",
    unapplied: "Statements that could not be applied",
    explanation: "FPL availability records and coach statements are evaluated separately.",
  },
};

export function ParticipationEvidence({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const evidence = view.participation_evidence;
  if (!evidence) return <RoleForecast view={view} />;
  const copy = COPY[language];
  const asOf =
    evidence.as_of && !Number.isNaN(new Date(evidence.as_of).getTime()) ? evidence.as_of : null;
  return (
    <details className={styles.adviceSection} data-testid="participation-evidence">
      <summary>{copy.title}</summary>
      <p>{copy.explanation}</p>
      <p className={styles.muted}>
        {copy.asOf}:{" "}
        {asOf ? <time dateTime={asOf}>{utcShort(asOf, locale)}</time> : copy.dateUnknown}
        {" · "}
        {evidence.gameweek === null
          ? copy.gameweekUnknown
          : messages.leagueMembers.windowWeekOf(evidence.gameweek)}
      </p>
      <ul className={styles.assumptionList}>
        <li>
          {copy.checked}: <span className="num">{evidence.captured_percentage_count}</span>.
        </li>
        <li>
          {copy.statements}: <span className="num">{evidence.manager_statement_count}</span>.
        </li>
        <li>
          {copy.applied}: <span className="num">{evidence.applied_player_count}</span>.
        </li>
        <li>
          {copy.unapplied}: <span className="num">{evidence.unapplied_statement_count}</span>.
        </li>
      </ul>
      {/* Nothing applied has three shapes: nothing was read, everything read was turned
          away, or statements were read and none reached a player. Each says which. */}
      {evidence.applied_player_count === 0 && (
        <p>
          {evidence.manager_statement_count === 0
            ? copy.noStatements
            : evidence.unapplied_statement_count >= evidence.manager_statement_count
              ? copy.allRejected
              : copy.noneApplied}
        </p>
      )}
      <StatementOutcomes view={view} />
      <RoleForecast view={view} />
    </details>
  );
}
