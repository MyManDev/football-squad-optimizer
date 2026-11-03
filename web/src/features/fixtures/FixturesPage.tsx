import { useSearchParams } from "react-router";

import { Card } from "../../design/components/Card";
import { EmptyState } from "../../design/components/EmptyState";
import { useLanguage } from "../../i18n/context";
import { useFixtures } from "./data";
import { DeadlineCalendar } from "./DeadlineCalendar";
import { FixtureChoice } from "./FixtureChoice";
import { FixtureMatrix } from "./FixtureMatrix";
import { FIXTURES_COPY } from "./fixturesCopy";
import { GameweekFixtures } from "./GameweekFixtures";
import { TeamFixtures } from "./TeamFixtures";
import { fixtureClubs, generalWeeks, weeksAhead } from "./weeks";
import styles from "./Fixtures.module.css";

/** The week choice's value for the whole run of weeks. */
const ALL_WEEKS = 0;

/**
 * The fixtures still to come, seen one of two ways: the general view, a matrix of every club
 * over the next five gameweeks or one of those weeks alone with its days and kickoffs, or one
 * club's matches to the end of the season. The choices stay in the address, so a reload or a
 * shared link opens the same view, and they replace it rather than add to it, so Back leaves
 * the page. Beside the title the deadlines still ahead can be taken into a calendar app as a
 * file.
 */
export function FixturesPage() {
  const { language, locale, messages } = useLanguage();
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
  const general = generalWeeks(ahead);
  const clubs = fixtureClubs(data);
  const club = clubs.find((team) => team.short_name === searchParams.get("team")) ?? clubs[0];
  const view = searchParams.get("view") === "team" ? "team" : "general";
  const asked = Number(searchParams.get("week"));
  const shownWeek = general.some((week) => week.gameweek === asked) ? asked : ALL_WEEKS;
  // The last week left has no matrix to be chosen from: it is simply the week on show.
  const oneWeek =
    general.length === 1 ? general[0] : general.find((week) => week.gameweek === shownWeek);

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
            <>
              {general.length > 1 ? (
                <FixtureChoice
                  legend={copy.weekLegend}
                  name="fixture-week"
                  value={shownWeek}
                  onChange={(next) => choose("week", next === ALL_WEEKS ? null : String(next))}
                  options={[
                    { value: ALL_WEEKS, label: messages.decision.week(general.length) },
                    ...general.map((week) => ({
                      value: week.gameweek,
                      label: messages.common.gameweekShort(week.gameweek),
                    })),
                  ]}
                />
              ) : null}
              {oneWeek ? (
                <Card title={messages.common.gameweek(oneWeek.gameweek)}>
                  <GameweekFixtures week={oneWeek} locale={locale} copy={copy} />
                </Card>
              ) : (
                <FixtureMatrix payload={data} weeks={general} copy={copy} />
              )}
            </>
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
