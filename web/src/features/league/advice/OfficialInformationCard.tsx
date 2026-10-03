import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import type { DecisionInformation } from "./informationFacts";
import styles from "../pages/LeagueMemberPage.module.css";
import { OfficialInjuryCard } from "./OfficialInjuryCard";

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
    bindings: "Önceki ve güncel kaynak bağlantıları",
    binding: "Bilgi",
    previous: "Gösterilen plan",
    latest: "Güncel girdiler",
    checkTime: "FPL kontrol zamanı",
    coachBinding: "Hoca haber kaynağı",
    minuteBinding: "Dakika ve puan bileşenleri",
    bound: "Bağlı",
    unbound: "Bağlı değil",
    notRecorded: "Kaydedilmemiş",
    sameBindings:
      "Bilgi sürümü değişmiş, ancak bu özet alanları aynı. Değişen kaynak içeriği bu alanlardan belirlenemez.",
    bindingLimit:
      "Kaynağın bağlı olması, bir açıklamanın uygulandığı veya puanların değiştiği anlamına gelmez. Kontrol zamanı haberin yayın zamanı değildir. Yeni sonuç yalnızca Hesapla ile istenir; gösterilen plan korunur.",
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
    bindings: "Previous and latest source bindings",
    binding: "Information",
    previous: "Displayed plan",
    latest: "Latest inputs",
    checkTime: "FPL check time",
    coachBinding: "Coach news source",
    minuteBinding: "Minute and point components",
    bound: "Bound",
    unbound: "Not bound",
    notRecorded: "Not recorded",
    sameBindings:
      "The information revision changed, but these summary fields are unchanged. They do not identify which source content changed.",
    bindingLimit:
      "A bound source does not mean a statement was applied or points changed. The check time is not the news publication time. Only Calculate requests a new result; the displayed plan is retained.",
  },
};

export function NewInformationNotice({
  view,
  latest,
}: {
  view: EntryAdvice;
  latest?: DecisionInformation;
}) {
  const { language, locale } = useLanguage();
  if (
    view.prediction_model?.id !== "football" ||
    !latest ||
    latest.source_snapshot_id !== view.source_snapshot_id ||
    latest.revision === view.decision_information?.revision
  )
    return null;
  const copy = COPY[language];
  const previous = view.decision_information;
  const stamp = (value: string | null | undefined) =>
    value ? <time dateTime={value}>{utcShort(value, locale)}</time> : copy.notRecorded;
  const binding = (value: boolean | undefined) =>
    value === undefined ? copy.notRecorded : value ? copy.bound : copy.unbound;
  const sameBindings =
    previous &&
    previous.observed_at === latest.observed_at &&
    previous.coach_news_bound === latest.coach_news_bound &&
    previous.minute_components_bound === latest.minute_components_bound;
  return (
    <div data-testid="new-information-notice">
      <p role="status" className={styles.honesty}>
        {previous ? copy.changed : copy.needsCheck}
      </p>
      <details className={styles.adviceSection} data-testid="information-binding-differences">
        <summary>{copy.bindings}</summary>
        {sameBindings && <p>{copy.sameBindings}</p>}
        <table style={{ width: "100%", tableLayout: "fixed", overflowWrap: "anywhere" }}>
          <thead>
            <tr>
              <th scope="col">{copy.binding}</th>
              <th scope="col">{copy.previous}</th>
              <th scope="col">{copy.latest}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{copy.checkTime}</th>
              <td>{stamp(previous?.observed_at)}</td>
              <td>{stamp(latest.observed_at)}</td>
            </tr>
            <tr>
              <th scope="row">{copy.coachBinding}</th>
              <td>{binding(previous?.coach_news_bound)}</td>
              <td>{binding(latest.coach_news_bound)}</td>
            </tr>
            <tr>
              <th scope="row">{copy.minuteBinding}</th>
              <td>{binding(previous?.minute_components_bound)}</td>
              <td>{binding(latest.minute_components_bound)}</td>
            </tr>
          </tbody>
        </table>
        <p className={styles.honesty}>{copy.bindingLimit}</p>
      </details>
    </div>
  );
}

/**
 * The central league injury source is disabled in production (the producer's
 * ``OFFICIAL_INJURY_SOURCE_ENABLED`` is False, with no override). The page mirrors that:
 * a payload carrying the central card is not drawn, whoever built it.
 */
export const OFFICIAL_INJURY_CARD_ENABLED = false;

export function OfficialInformationCard({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const feed = view.official_information;
  if (!feed) {
    return OFFICIAL_INJURY_CARD_ENABLED ? (
      <OfficialInjuryCard data={view.official_injuries} />
    ) : null;
  }
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
      {OFFICIAL_INJURY_CARD_ENABLED ? (
        <OfficialInjuryCard
          data={view.official_injuries}
          playerNames={Object.fromEntries(
            feed.players.map((player) => [player.player_id, player.name]),
          )}
        />
      ) : null}
    </details>
  );
}
