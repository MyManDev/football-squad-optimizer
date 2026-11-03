import { useSearchParams } from "react-router";

import { EmptyState } from "../../design/components/EmptyState";
import { useLanguage } from "../../i18n/context";
import { useFixtures } from "./data";
import { DeadlineCalendar } from "./DeadlineCalendar";
import { FixtureChoice } from "./FixtureChoice";
import { FixtureMatrix } from "./FixtureMatrix";
import { FIXTURES_COPY } from "./fixturesCopy";
import { TeamFixtures } from "./TeamFixtures";
import { fixtureClubs, generalWeeks, weeksAhead } from "./weeks";
import styles from "./Fixtures.module.css";

/**
 * The fixtures still to come, seen one of two ways: the general view, a matrix of every club
 * over the next five gameweeks that rolls on by itself as the weeks pass, or one club's matches
 * to the end of the season. The choices stay in the address, so a reload or a shared link opens
 * the same view, and they replace it rather than add to it, so Back leaves the page. Beside the
 * title the deadlines still ahead can be taken into a calendar app as a file.
 */
export function FixturesPage() {
  const { language, messages } = useLanguage();
  const copy = FIXTURES_COPY[language];
  const { data, isPending } = useFixtures();
  const [searchParams, setSearchParams] = useSearchParams();
  if (isPending) return <EmptyState title={messages.common.loading} />;
  if (!data) return <EmptyState page title={copy.notPublished} />;

  const choose = (name: string, value: string | null) =>
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value === null) next.delete(name);
        else next.set(name, value);
        return next;
      },
      { replace: true },
    );

  const ahead = weeksAhead(data);
  const clubs = fixtureClubs(data);
  const club = clubs.find((team) => team.short_name === searchParams.get("team")) ?? clubs[0];
  const view = searchParams.get("view") === "team" ? "team" : "general";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.kicker}>{data.season}</div>
          <h1 className={styles.pageTitle}>{copy.pageTitle}</h1>
        </div>
        <DeadlineCalendar payload={data} copy={copy} />
      </header>
      {ahead.length > 0 && club ? (
        <>
          <FixtureChoice
            legend={copy.viewLegend}
            name="fixture-view"
            value={view}
            onChange={(next) => choose("view", next === "team" ? next : null)}
            options={[
              { value: "general", label: copy.generalView },
              { value: "team", label: copy.teamView },
            ]}
          />
          {view === "team" ? (
            <TeamFixtures
              payload={data}
              clubs={clubs}
              club={club}
              onChoose={(code) => choose("team", code)}
              copy={copy}
            />
          ) : (
            <FixtureMatrix payload={data} weeks={generalWeeks(ahead)} copy={copy} />
          )}
        </>
      ) : data.unscheduled_count === 0 ? (
        <p className={styles.lede}>{copy.noneAhead}</p>
      ) : null}
      {data.unscheduled_count > 0 ? (
        <p className={styles.lede}>{copy.unscheduledCount(data.unscheduled_count)}</p>
      ) : null}
    </div>
  );
}
