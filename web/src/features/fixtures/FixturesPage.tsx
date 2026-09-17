import { Card } from "../../design/components/Card";
import { EmptyState } from "../../design/components/EmptyState";
import { useLanguage } from "../../i18n/context";
import { local } from "../../lib/format";
import { fixtureWeeks, useFixtures } from "./data";
import { FIXTURES_COPY } from "./fixturesCopy";
import { GameweekFixtures } from "./GameweekFixtures";
import type { FixtureGameweek } from "./types";
import styles from "./Fixtures.module.css";

/** This week and next at the top, then every played gameweek, newest first. */
export function FixturesPage() {
  const { language, locale, messages } = useLanguage();
  const copy = FIXTURES_COPY[language];
  const { data, isPending } = useFixtures();
  if (isPending) return <EmptyState title={messages.common.loading} />;
  if (!data) return <EmptyState title={copy.notPublished} />;
  const { current, next, past } = fixtureWeeks(data);

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
      <div className={styles.pageWeek}>
        <GameweekFixtures week={entry} locale={locale} copy={copy} />
      </div>
    </Card>
  );

  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>{data.season}</div>
        <h1 className={styles.pageTitle}>{copy.pageTitle}</h1>
        <p className={styles.lede}>{copy.pageLede}</p>
      </header>
      {current ? week(current, copy.thisWeek) : null}
      {next ? week(next, copy.nextWeek) : null}
      <h2 className={styles.pastTitle}>{copy.pastTitle}</h2>
      {past.length === 0 ? (
        <p className={styles.lede}>{copy.noPast}</p>
      ) : (
        past.map((entry) => week(entry))
      )}
      <p className={styles.lede}>
        {copy.capturedAt(local(data.captured_at_utc, locale))}
        {data.unscheduled_count > 0 ? ` ${copy.unscheduledCount(data.unscheduled_count)}` : null}
      </p>
    </div>
  );
}
