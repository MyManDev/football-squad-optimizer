import { Card } from "../../design/components/Card";
import { ClubSwatch } from "../../design/components/ClubSwatch";
import { useLanguage } from "../../i18n/context";
import { FixtureChoice } from "./FixtureChoice";
import type { FixturesCopy } from "./fixturesCopy";
import { fixtureDay, fixtureTime } from "./kickoff";
import type { FixtureTeam, FixturesPayload } from "./types";
import { clubWeeksAhead, type ClubFixture } from "./weeks";
import styles from "./TeamFixtures.module.css";

/** One match of the chosen club's run: its week, its opponent and venue, and when it is. */
function MatchCell({
  gameweek,
  match,
  copy,
}: {
  gameweek: number;
  match: ClubFixture;
  copy: FixturesCopy;
}) {
  const { locale, messages } = useLanguage();
  const members = messages.leagueMembers;
  const kickoff = match.fixture.kickoff_utc;
  return (
    <li className={styles.match} data-venue={match.home ? "home" : "away"}>
      <span className={`${styles.week} num`}>{messages.common.gameweekShort(gameweek)}</span>
      <span className={styles.venue}>
        <span aria-hidden="true">{match.home ? members.fixtureHome : members.fixtureAway}</span>
        <span className="visually-hidden">{match.home ? copy.atHome : copy.away}</span>
      </span>
      <span className={styles.opponent} title={match.opponent.name}>
        <ClubSwatch code={match.opponent.short_name} split />
        {match.opponent.short_name} <span className="visually-hidden">{match.opponent.name}</span>
      </span>
      <span className={styles.when}>
        {kickoff === null ? copy.unscheduled : fixtureDay(kickoff, locale)}
      </span>
      {kickoff === null ? null : (
        <time className={`${styles.when} num`} dateTime={kickoff}>
          {fixtureTime(kickoff, locale)}
        </time>
      )}
    </li>
  );
}

/**
 * One club's fixtures still to come, to the end of the season: a choice of the twenty clubs,
 * then a grid of its weeks that reads across and down, with a home match filled and an away
 * match outlined as in the matrix. A week it does not play says so, and a double week is two
 * cells.
 */
export function TeamFixtures({
  payload,
  clubs,
  club,
  onChoose,
  copy,
}: {
  payload: FixturesPayload;
  clubs: readonly FixtureTeam[];
  club: FixtureTeam;
  onChoose: (code: string) => void;
  copy: FixturesCopy;
}) {
  const { messages } = useLanguage();
  const weeks = clubWeeksAhead(payload, club.short_name);
  return (
    <>
      <FixtureChoice
        clubs
        legend={copy.clubLegend}
        name="fixture-club"
        value={club.short_name}
        onChange={onChoose}
        options={clubs.map((option) => ({
          value: option.short_name,
          title: option.name,
          label: (
            <>
              <ClubSwatch code={option.short_name} split />
              {option.short_name} <span className="visually-hidden">{option.name}</span>
            </>
          ),
        }))}
      />
      <Card title={club.name}>
        {weeks.length === 0 ? (
          <p className={styles.none}>{copy.noneAhead}</p>
        ) : (
          <ul className={styles.grid}>
            {weeks.flatMap(({ gameweek, matches }) =>
              matches.length === 0
                ? [
                    <li key={`blank-${gameweek}`} className={styles.match} data-venue="none">
                      <span className={`${styles.week} num`}>
                        {messages.common.gameweekShort(gameweek)}
                      </span>
                      <span className={styles.blank}>{messages.leagueMembers.fixtureNone}</span>
                    </li>,
                  ]
                : matches.map((match) => (
                    <MatchCell
                      key={match.fixture.fixture_id}
                      gameweek={gameweek}
                      match={match}
                      copy={copy}
                    />
                  )),
            )}
          </ul>
        )}
      </Card>
    </>
  );
}
