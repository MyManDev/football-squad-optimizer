import { CountingNumber } from "../../../design/CountingNumber";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import type { EntryAdvice } from "../types";
import styles from "../pages/LeagueMemberPage.module.css";

const COPY = {
  tr: {
    title: "Beklenen puan",
    net: "Ceza sonrası beklenen puan",
  },
  en: {
    title: "Expected Points",
    net: "Expected Points After Hits",
  },
};

export function ExpectedLineup({ view }: { view: EntryAdvice }) {
  const { language, locale } = useLanguage();
  const expectation = view.lineup_expectation;
  if (!expectation) return null;
  const copy = COPY[language];
  return (
    <section
      className={styles.adviceSection}
      aria-label={copy.title}
      data-testid="lineup-expectation"
    >
      <h3 className={styles.lineupTitle}>{copy.title}</h3>
      <p>
        {copy.net}:{" "}
        <strong className="num">
          <CountingNumber
            countKey={`net:${view.league_id}:${view.entry_id}:${view.gameweek}`}
            value={expectation.expected_net_points}
            format={(value) => points(value, 1, locale)}
          />
        </strong>
      </p>
    </section>
  );
}
