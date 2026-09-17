import type { FixturesCopy } from "./fixturesCopy";
import type { Fixture, FixtureGameweek } from "./types";
import styles from "./Fixtures.module.css";

function day(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

function time(iso: string, locale: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Consecutive fixtures sharing a local day; the producer already sorted them by kickoff. */
function byDay(fixtures: Fixture[], locale: string, unscheduled: string) {
  const groups: { label: string; fixtures: Fixture[] }[] = [];
  for (const fixture of fixtures) {
    const label = fixture.kickoff_utc === null ? unscheduled : day(fixture.kickoff_utc, locale);
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
      {time(fixture.kickoff_utc, locale)}
    </time>
  );
}

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
                </span>
                <Middle fixture={fixture} locale={locale} copy={copy} />
                <span className={styles.away} title={fixture.away.name}>
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
