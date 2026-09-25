import { Card } from "../../design/components/Card";
import { EmptyState } from "../../design/components/EmptyState";
import { useLanguage } from "../../i18n/context";
import { local } from "../../lib/format";
import { upcomingFixtureWeeks, useFixtures } from "./data";
import { FIXTURES_COPY } from "./fixturesCopy";
import { GameweekFixtures } from "./GameweekFixtures";
import type { FixtureGameweek } from "./types";
import styles from "./Fixtures.module.css";

/**
 * This week and next at the top, then every played gameweek, newest first. The weeks stand
 * side by side where the column has room for more than one, so a wide screen reads the
 * schedule like a fixture board instead of one narrow list down the page.
 */
export function FixturesPage() {
  const { language, locale, messages } = useLanguage();
  const copy = FIXTURES_COPY[language];
  const { data, isPending } = useFixtures();
  if (isPending) return <EmptyState title={messages.common.loading} />;
  if (!data) return <EmptyState title={copy.notPublished} />;
  const { current, next, past } = upcomingFixtureWeeks(data);

  const week = (entry: FixtureGameweek, label?: string) => (
    <Card
      key={entry.gameweek}
      title={
        label
          ? `${label} · ${messages.common.gameweek(entry.gameweek)}`
          : messages.common.gameweek(entry.gameweek)
      }
      aside={copy.deadline(local(entry.deadline_utc, locale))}
    >
      <GameweekFixtures week={entry} locale={locale} copy={copy} />
    </Card>
  );

  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>{data.season}</div>
        <h1 className={styles.pageTitle}>{copy.pageTitle}</h1>
        <p className={styles.lede}>{copy.pageLede}</p>
      </header>
      {current || next ? (
        <div className={styles.weeks}>
          {current ? week(current, copy.thisWeek) : null}
          {next ? week(next, copy.nextWeek) : null}
        </div>
      ) : null}
      <h2 className={styles.pastTitle}>{copy.pastTitle}</h2>
      {past.length === 0 ? (
        <p className={styles.lede}>{copy.noPast}</p>
      ) : (
        <div className={styles.weeks}>{past.map((entry) => week(entry))}</div>
      )}
      <p className={styles.lede}>
        {copy.capturedAt(local(data.captured_at_utc, locale))}
        {data.unscheduled_count > 0 ? ` ${copy.unscheduledCount(data.unscheduled_count)}` : null}
      </p>
    </div>
  );
}
