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
    applied: "Doğrulanmış haberin uygulandığı oyuncu",
    unapplied: "Uygulanamayan açıklama",
    explanation:
      "FPL oynayabilirlik kayıtları ile hoca açıklamaları ayrı değerlendirilir. Belirsiz açıklamalar tek başına tahmini değiştirmez.",
    rules: {
      source_eligibility_only:
        "Açıklamalar oyuncunun oynayabilmesiyle ilgili bilgi sağlar; ilk 11 garantisi sayılmaz.",
      no_start_or_minutes_reestimate:
        "Bu haberler, ilk 11’de başlama veya süre için ayrı bir tahmin üretmez.",
      explicit_full_match_restriction:
        "Maçın tamamını oynayamayacağı açıkça belirtilen oyuncunun tam maç süresi, modelin öğrendiği daha kısa sürelere dağıtılır.",
      no_start_reestimate: "Bu işlem, ilk 11’de başlama için yeni bir tahmin üretmez.",
      appearance_unchanged_by_minute_evidence:
        "Süre kısıtı, oyuncunun sahaya çıkmasıyla ilgili mevcut tahmini değiştirmez; ayrı bir yokluk haberi ayrıca değerlendirilir.",
      club_attack_shares_reallocated:
        "Takımın gol ve asist toplamı korunur; oyuncular arasındaki paylar değişen sürelere göre yeniden dağıtılır.",
      declared_minute_intervention_not_calibration:
        "Bu süre değişikliği açık bir model varsayımıdır; haber etiketlerinden öğrenilmiş bir sayısal dönüşüm değildir.",
      minute_evidence_not_applied:
        "Bazı süre açıklamaları gerekli kaynak, maç kapsamı veya model bileşenleri doğrulanamadığı için uygulanmadı.",
      no_external_calibration:
        "Nitel açıklamalar için dışarıdan doğrulanmış bir sayısal dönüşüm bulunmuyor.",
      future_values_not_recovered:
        "Mevcut tahminde sıfır olan gelecek hafta değerleri, yeni haberle kendiliğinden geri kazanılmaz.",
      unsupported_appearance_contract:
        "Bu tahminde kullanılabilir sahaya çıkma verisi bulunmadığı için haberlerden sayısal güncelleme yapılmadı.",
    },
  },
  en: {
    title: "How was playing news used?",
    checked: "FPL availability records checked",
    statements: "Coach statements considered",
    asOf: "Information as of",
    dateUnknown: "Date not reported",
    gameweekUnknown: "Gameweek not reported",
    noneApplied: "No coach statement was applied to this forecast.",
    applied: "Players with verified statements applied",
    unapplied: "Statements that could not be applied",
    explanation:
      "FPL availability records and coach statements are evaluated separately. Uncertain statements alone do not change the forecast.",
    rules: {
      source_eligibility_only:
        "Statements describe whether a player can appear; they do not guarantee a start.",
      no_start_or_minutes_reestimate:
        "This news does not produce separate forecasts of starts or minutes.",
      explicit_full_match_restriction:
        "When a player is explicitly ruled out of a full match, the model redistributes full-match time across its learned shorter durations.",
      no_start_reestimate: "This operation does not produce a new starting-lineup forecast.",
      appearance_unchanged_by_minute_evidence:
        "A minute restriction preserves the current appearance forecast; a separate absence statement is evaluated separately.",
      club_attack_shares_reallocated:
        "The club's goal and assist totals stay fixed; players' shares are redistributed using the changed minutes.",
      declared_minute_intervention_not_calibration:
        "This minute change is an explicit model assumption, not a numerical mapping learned from news labels.",
      minute_evidence_not_applied:
        "Some minute statements were not applied because the required source, match scope or model components could not be verified.",
      no_external_calibration:
        "There is no externally validated numerical conversion for qualitative statements.",
      future_values_not_recovered:
        "Future-week values already at zero in the forecast are not automatically recovered from new statements.",
      unsupported_appearance_contract:
        "This forecast has no usable participation data, so statements did not produce a numerical update.",
    },
  },
};

export function ParticipationEvidence({ view }: { view: EntryAdvice }) {
  const { language, locale, messages } = useLanguage();
  const evidence = view.participation_evidence;
  if (!evidence) return <RoleForecast view={view} />;
  const copy = COPY[language];
  const asOf =
    evidence.as_of && !Number.isNaN(new Date(evidence.as_of).getTime()) ? evidence.as_of : null;
  const assumptions = [...new Set(evidence.assumptions)]
    .filter((rule): rule is keyof typeof copy.rules => Object.hasOwn(copy.rules, rule))
    .map((rule) => copy.rules[rule]);
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
      {evidence.applied_player_count === 0 && <p>{copy.noneApplied}</p>}
      <StatementOutcomes view={view} />
      <RoleForecast view={view} />
      <ul className={styles.assumptionList}>
        {assumptions.map((assumption) => (
          <li key={assumption}>{assumption}</li>
        ))}
      </ul>
    </details>
  );
}
