import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import type { DecisionInformation } from "./informationFacts";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "FPL bilgileri ve bu plan",
    observed: "FPL bilgileri kontrol edildi",
    coverage: "takımın oyuncu bilgileri okunmuş",
    players: "oyuncu",
    source: "Resmi FPL kaynağı",
    sourceDate: "Haberin kaynak tarihi",
    noDate: "Kaynak tarih belirtmedi",
    sourceValue: "FPL oynama değeri",
    noValue: "Oynama değeri bildirilmedi",
    status: {
      a: "Uygun",
      d: "Şüpheli",
      i: "Sakat",
      s: "Cezalı",
      u: "Kullanılamıyor",
      n: "Kadro dışı",
    },
    unknown: "Kaynakta farklı durum kodu var",
    cleared: "Önceki haber metni temizlenmiş.",
    note: "Bu değerler FPL kaydından gelir; ilk 11’de başlama garantisi veya ayrı bir dakika tahmini değildir. Kontrol tarihi, haberin yayın tarihi değildir.",
    age: "Sunucunun çalışıyor olması, bu bilgilerin şimdi güncellendiği anlamına gelmez.",
    noFlags: "Bu plandaki oyuncular için gösterilecek FPL uyarısı yok.",
    changed:
      "Bu plan hesaplandıktan sonra karar girdileri değişmiş. Yeni bilgilerle hesaplamak için Hesapla düğmesini kullanabilirsin. Gösterilen eski plan kendiliğinden değiştirilmedi.",
    needsCheck:
      "Bu plan bilgi sürümünü taşımıyor. Güncel girdilerle hesaplayarak yeni sonucu karşılaştırabilirsin.",
  },
  en: {
    title: "FPL information and this plan",
    observed: "FPL information checked",
    coverage: "clubs have player information",
    players: "players",
    source: "Official FPL source",
    sourceDate: "Source news date",
    noDate: "Source date not reported",
    sourceValue: "FPL playing value",
    noValue: "Playing value not reported",
    status: {
      a: "Available",
      d: "Doubtful",
      i: "Injured",
      s: "Suspended",
      u: "Unavailable",
      n: "Not in squad",
    },
    unknown: "Another source status code",
    cleared: "The earlier news text was cleared.",
    note: "These values come from FPL; they do not guarantee a start or provide a separate minute forecast. The check time is not the publication time.",
    age: "A healthy server does not mean this information was refreshed just now.",
    noFlags: "No FPL alerts to show for the players in this plan.",
    changed:
      "Decision inputs changed after this plan was calculated. Use Calculate to request a result with the new information. The displayed earlier plan has not been changed automatically.",
    needsCheck:
      "This plan has no information revision. Calculate with the current inputs to compare a new result.",
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
      {view.decision_information ? COPY[language].changed : COPY[language].needsCheck}
    </p>
  );
}

export function OfficialInformationCard({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const feed = view.official_information;
  if (!feed) return null;
  const copy = COPY[language];
  const flagged = feed.players.filter(
    (p) =>
      p.status !== "a" ||
      (p.source_chance_percent !== null && p.source_chance_percent !== 100) ||
      p.news_state !== "not_reported",
  );
  return (
    <details className={styles.adviceSection} data-testid="official-information">
      <summary>{copy.title}</summary>
      <p>
        {feed.team_count}/{feed.declared_team_count} {copy.coverage}; {feed.player_count}{" "}
        {copy.players}.
      </p>
      <p>
        {copy.observed}:{" "}
        <time dateTime={feed.observed_at}>{utcShort(feed.observed_at, locale)}</time>
      </p>
      <p className={styles.muted}>
        {copy.note} {copy.age}
      </p>
      <a href={feed.source_url} target="_blank" rel="noreferrer">
        {copy.source}
      </a>
      {flagged.length === 0 ? (
        <p>{copy.noFlags}</p>
      ) : (
        <ul className={styles.assumptionList}>
          {flagged.map((p) => (
            <li key={p.player_id}>
              <strong>{p.name}</strong> · {p.team_name} ·{" "}
              {Object.hasOwn(copy.status, p.status)
                ? copy.status[p.status as keyof typeof copy.status]
                : copy.unknown}
              <p>
                {p.source_chance_percent === null
                  ? copy.noValue
                  : String(copy.sourceValue + ": " + p.source_chance_percent + "/100")}
              </p>
              <p>
                {copy.sourceDate}:{" "}
                {p.source_added_at ? (
                  <time dateTime={p.source_added_at}>{utcShort(p.source_added_at, locale)}</time>
                ) : (
                  copy.noDate
                )}
              </p>
              {p.news_state === "cleared" && <p>{copy.cleared}</p>}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
