import { useLanguage } from "../../../i18n/context";
import { utcShort } from "../../../lib/format";
import type { CoachAbsence } from "../advice/coachAbsences";
import styles from "./CoachNews.module.css";

const COPY = {
  tr: { mark: "Yok", title: "Hocanın açıklaması", out: "Hoca: bu maçta yok", source: "Haberi oku" },
  en: {
    mark: "Out",
    title: "Manager's statement",
    out: "Manager: out for this match",
    source: "Read the news",
  },
};

/** A source link beside the player's points, with a full accessible statement. */
export function CoachNewsMark({ news, name }: { news: CoachAbsence; name: string }) {
  const { language } = useLanguage();
  const copy = COPY[language];
  return (
    <a
      className={styles.mark}
      href={news.sourceUrl}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${name}: ${copy.out}. ${copy.source}`}
      data-coach-absence=""
    >
      {copy.mark}
    </a>
  );
}

/** Quotes stay beside their player and remain readable without hovering. */
export function CoachNews({
  news,
  players,
}: {
  news: ReadonlyMap<number, CoachAbsence>;
  players: ReadonlyMap<number, string>;
}) {
  const { language, locale } = useLanguage();
  const copy = COPY[language];
  const rows = [...news.values()].filter((item) => players.has(item.playerId));
  if (rows.length === 0) return null;
  return (
    <section className={styles.news} aria-label={copy.title}>
      <h3 className={styles.heading}>{copy.title}</h3>
      <ul className={styles.list}>
        {rows.map((item) => (
          <li key={item.playerId} className={styles.item}>
            <strong>{players.get(item.playerId)}</strong>
            <p className={styles.out}>{copy.out}</p>
            <blockquote className={styles.quote}>{item.words}</blockquote>
            <div className={styles.source}>
              <a href={item.sourceUrl} target="_blank" rel="noopener noreferrer">
                {copy.source}
              </a>
              <time dateTime={item.publishedAt}>{utcShort(item.publishedAt, locale)}</time>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
