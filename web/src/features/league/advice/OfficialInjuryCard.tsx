import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import {
  isInjurySourceInstant,
  safeInjurySourceUrl,
  type OfficialInjuryFacts,
} from "./officialInjuryFacts";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Premier League sakatlık listesi",
    coverage: "takımın kaynak bölümü okundu",
    listed: "listelenen kayıt",
    mapped: "oyuncuyla eşleşen kayıt",
    missing: "Bölümü alınamayan takımlar",
    incomplete: "Eksik okunmuş bölümler",
    unknown: "Bu sezonun takımlarıyla eşleşmeyen kaynak başlıkları",
    updated: "Sayfanın bildirdiği güncelleme",
    observed: "Kaynak kontrol edildi",
    noDate: "Tarih bildirilmedi",
    rowDate: "Kaydın kaynak tarihi",
    source: "Resmi Premier League kaynağı",
    detail: "Ayrıntı kaynağı",
    injury: "Kaynağın belirttiği durum",
    noInjury: "Durum belirtilmedi",
    empty: "Bu plandaki oyuncular için gösterilecek kaynak kaydı yok.",
  },
  en: {
    title: "Premier League injury list",
    coverage: "club source sections read",
    listed: "listed records",
    mapped: "records matched to players",
    missing: "Club sections not obtained",
    incomplete: "Incomplete sections",
    unknown: "Source headings not matched to this season's clubs",
    updated: "Update stated by the page",
    observed: "Source checked",
    noDate: "Date not reported",
    rowDate: "Record's source date",
    source: "Official Premier League source",
    detail: "Details source",
    injury: "Condition stated by the source",
    noInjury: "Condition not stated",
    empty: "No source records to display for the players in this plan.",
  },
};

export function OfficialInjuryCard({
  data,
  playerNames = {},
}: {
  data?: OfficialInjuryFacts;
  playerNames?: Readonly<Record<number, string>>;
}) {
  const { language, locale } = useLanguage();
  if (!data) return null;
  const copy = COPY[language];
  const rows = data.facts.filter((fact) => playerNames[fact.player_id]?.trim());
  const stamp = (value: string | null) =>
    isInjurySourceInstant(value) ? (
      <time dateTime={value}>{utcShort(value, locale)}</time>
    ) : (
      <span>{value || copy.noDate}</span>
    );
  return (
    <details className={styles.adviceSection} data-testid="official-injuries">
      <summary>{copy.title}</summary>
      <p>
        {data.received_clubs.length}/{data.roster_clubs.length} {copy.coverage}; {data.listed_rows}{" "}
        {copy.listed}, {data.mapped_rows} {copy.mapped}.
      </p>
      <p>
        {copy.updated}: {stamp(data.source_updated_at)}
        <br />
        {copy.observed}: {stamp(data.observed_at)}
      </p>
      <ul className={styles.assumptionList}>
        {data.missing_clubs.length > 0 && (
          <li>
            {copy.missing}: {data.missing_clubs.join(", ")}
          </li>
        )}
        {data.incomplete_clubs.length > 0 && (
          <li>
            {copy.incomplete}: {data.incomplete_clubs.join(", ")}
          </li>
        )}
        {data.unknown_source_clubs.length > 0 && (
          <li>
            {copy.unknown}: {data.unknown_source_clubs.join(", ")}
          </li>
        )}
      </ul>
      <a href={data.source_url} target="_blank" rel="noreferrer">
        {copy.source}
      </a>
      {rows.length === 0 ? (
        <p>{copy.empty}</p>
      ) : (
        <ul className={styles.assumptionList}>
          {rows.map((fact, index) => (
            <li key={`${fact.player_id}-${index}`}>
              <strong>{playerNames[fact.player_id]}</strong> · {fact.club}
              <p>
                {copy.injury}: {fact.injury || copy.noInjury}
              </p>
              <p>
                {copy.rowDate}: {stamp(fact.source_date)}
              </p>
              {fact.details_urls.filter(safeInjurySourceUrl).map((url, link) => (
                <p key={url}>
                  <a href={url} target="_blank" rel="noreferrer">
                    {copy.detail}
                    {fact.details_urls.length > 1 ? ` ${link + 1}` : ""}
                  </a>
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
