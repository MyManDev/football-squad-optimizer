import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Beklenen puan nasıl hesaplandı?",
    explanation:
      "İlk 11, oynayamayanların yerine girebilen yedekler ve kaptan oynamazsa yardımcı kaptana geçen ek puan birlikte hesaplanır. Yedeklere sabit bir puan payı eklenmez.",
    starting_points: "İlk 11",
    autosub_points: "Otomatik değişikliklerden gelen puan",
    captain_bonus_points: "Kaptanın ek puanı",
    vice_bonus_points: "Kaptan oynamazsa yardımcısının ek puanı",
    bench_boost_points: "Yedek Gücü puanı",
    hits: "Transfer cezası",
    net: "Ceza sonrası beklenen puan",
  },
  en: {
    title: "How are expected points calculated?",
    explanation:
      "The starting eleven, eligible automatic substitutes and the vice-captain bonus when the captain does not play are scored together. No fixed share of bench points is added.",
    starting_points: "Starting eleven",
    autosub_points: "Automatic substitute points",
    captain_bonus_points: "Captain bonus",
    vice_bonus_points: "Vice-captain bonus when the captain does not play",
    bench_boost_points: "Bench Boost points",
    hits: "Transfer hits",
    net: "Expected points after hits",
  },
};

export function ExpectedLineup({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const expectation = view.lineup_expectation;
  if (!expectation) return null;
  const copy = COPY[language];
  const terms = [
    "starting_points",
    "autosub_points",
    "captain_bonus_points",
    "vice_bonus_points",
    "bench_boost_points",
  ] as const;
  return (
    <section
      className={styles.adviceSection}
      aria-label={copy.title}
      data-testid="lineup-expectation"
    >
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p className={styles.muted}>{copy.explanation}</p>
      <ul>
        {terms.map((term) => (
          <li key={term}>
            {copy[term]}: <strong className="num">{points(expectation[term], 1, locale)}</strong>
          </li>
        ))}
        {typeof view.transfer_hit_points === "number" ? (
          <li>
            {copy.hits}: <span className="num">{points(view.transfer_hit_points, 1, locale)}</span>
          </li>
        ) : null}
      </ul>
      <p>
        {copy.net}:{" "}
        <strong className="num">{points(expectation.expected_net_points, 1, locale)}</strong>
      </p>
    </section>
  );
}
