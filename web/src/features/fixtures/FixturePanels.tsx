import { Link, useLocation } from "react-router";

import { useLanguage } from "../../i18n/context";
import { local } from "../../lib/format";
import { upcomingFixtureWeeks, useFixtures } from "./data";
import { FIXTURES_COPY } from "./fixturesCopy";
import { GameweekFixtures } from "./GameweekFixtures";
import type { FixtureGameweek } from "./types";
import styles from "./Fixtures.module.css";

function Panel({ title, week }: { title: string; week: FixtureGameweek }) {
  const { language, locale, messages } = useLanguage();
  const copy = FIXTURES_COPY[language];
  return (
    <>
      <header className={styles.panelHead}>
        <h2 className={styles.panelTitle}>{title}</h2>
        <span className={styles.panelWeek}>{messages.common.gameweekShort(week.gameweek)}</span>
      </header>
      <p className={styles.deadline}>{copy.deadline(local(week.deadline_utc, locale))}</p>
      <GameweekFixtures week={week} locale={locale} copy={copy} />
      <Link className={styles.pastLink} to="/fixtures">
        {copy.pastLink}
      </Link>
    </>
  );
}

/**
 * This week's fixtures in the left margin, next week's in the right, beside the page's
 * own column. Where the margins are too narrow for them, the same two lists sit closed
 * under the page. Which of the two shows is the stylesheet's decision, so there is no
 * layout flash and no listener.
 *
 * A tree with no fixture list renders nothing at all.
 */
export function FixturePanels() {
  const { language, locale } = useLanguage();
  const { pathname } = useLocation();
  const { data } = useFixtures();
  // The fixtures page lists both weeks itself.
  if (!data || pathname === "/fixtures") return null;
  const { current, next } = upcomingFixtureWeeks(data);
  if (!current) return null;
  const copy = FIXTURES_COPY[language];
  return (
    <>
      <aside className={`${styles.rail} ${styles.railLeft}`} aria-label={copy.thisWeek}>
        <Panel title={copy.thisWeek} week={current} />
        <small className={styles.deadline}>
          {copy.capturedAt(local(data.captured_at_utc, locale))}
        </small>
      </aside>
      {next ? (
        <aside className={`${styles.rail} ${styles.railRight}`} aria-label={copy.nextWeek}>
          <Panel title={copy.nextWeek} week={next} />
          <small className={styles.deadline}>
            {copy.capturedAt(local(data.captured_at_utc, locale))}
          </small>
        </aside>
      ) : null}
      <details className={styles.stacked}>
        <summary className={styles.stackedSummary}>{copy.summary}</summary>
        <div className={styles.stackedBody}>
          <p className={styles.deadline}>{copy.capturedAt(local(data.captured_at_utc, locale))}</p>
          <section>
            <Panel title={copy.thisWeek} week={current} />
          </section>
          {next ? (
            <section>
              <Panel title={copy.nextWeek} week={next} />
            </section>
          ) : null}
        </div>
      </details>
    </>
  );
}
