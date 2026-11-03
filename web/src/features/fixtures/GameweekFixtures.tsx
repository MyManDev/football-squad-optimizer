import { ClubSwatch } from "../../design/components/ClubSwatch";
import { fixtureDay, fixtureTime } from "./kickoff";
import type { FixturesCopy } from "./fixturesCopy";
import type { Fixture, FixtureGameweek } from "./types";
import styles from "./Fixtures.module.css";

/** Consecutive fixtures sharing a local day; the producer already sorted them by kickoff. */
function byDay(fixtures: Fixture[], locale: string, unscheduled: string) {
  const groups: { label: string; fixtures: Fixture[] }[] = [];
  for (const fixture of fixtures) {
    const label =
      fixture.kickoff_utc === null ? unscheduled : fixtureDay(fixture.kickoff_utc, locale);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.fixtures.push(fixture);
    else groups.push({ label, fixtures: [fixture] });
  }
  return groups;
}

function Middle({
  fixture,
  locale,
  copy,
}: {
  fixture: Fixture;
  locale: string;
  copy: FixturesCopy;
}) {
  // A score is a result only at full time, and only when the record has both halves of it.
  if (fixture.finished && fixture.home_score !== null && fixture.away_score !== null) {
    return (
      <span className={`${styles.score} num`}>
        {fixture.home_score} - {fixture.away_score}
      </span>
    );
  }
  if (fixture.kickoff_utc === null) return <span className={styles.when}>{copy.versus}</span>;
  return (
    <time className={`${styles.when} num`} dateTime={fixture.kickoff_utc}>
      {fixtureTime(fixture.kickoff_utc, locale)}
    </time>
  );
}

/**
 * One gameweek's fixtures grouped by local day. Each club is printed by its code with its
 * two colours beside it, on the side facing the middle, so a row reads the same from both
 * ends. The days stand side by side where the column holds them.
 */
export function GameweekFixtures({
  week,
  locale,
  copy,
}: {
  week: FixtureGameweek;
  locale: string;
  copy: FixturesCopy;
}) {
  if (week.fixtures.length === 0) return <p className={styles.empty}>{copy.noFixtures}</p>;
  return (
    <div className={styles.days}>
      {byDay(week.fixtures, locale, copy.unscheduled).map((group) => (
        <div key={group.label}>
          <div className={styles.day}>{group.label}</div>
          <ul className={styles.rows}>
            {group.fixtures.map((fixture) => (
              <li key={fixture.fixture_id} className={styles.row}>
                <span className={styles.home} title={fixture.home.name}>
                  {fixture.home.short_name}
                  <ClubSwatch code={fixture.home.short_name} split />
                </span>
                <Middle fixture={fixture} locale={locale} copy={copy} />
                <span className={styles.away} title={fixture.away.name}>
                  <ClubSwatch code={fixture.away.short_name} split />
                  {fixture.away.short_name}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
