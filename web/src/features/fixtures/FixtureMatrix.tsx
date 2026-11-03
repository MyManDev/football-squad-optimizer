import { ClubSwatch } from "../../design/components/ClubSwatch";
import { useLanguage } from "../../i18n/context";
import type { FixturesCopy } from "./fixturesCopy";
import type { FixtureGameweek, FixturesPayload } from "./types";
import { clubMatrix, type ClubFixture } from "./weeks";
import styles from "./FixtureMatrix.module.css";

function Match({ match, copy }: { match: ClubFixture; copy: FixturesCopy }) {
  const members = useLanguage().messages.leagueMembers;
  return (
    <span
      className={styles.match}
      data-venue={match.home ? "home" : "away"}
      data-behind={match.behind ? "" : undefined}
      title={match.opponent.name}
    >
      <ClubSwatch code={match.opponent.short_name} split />
      <span className={styles.opponent}>{match.opponent.short_name}</span>
      <span className={styles.venue}>
        <span aria-hidden="true">{match.home ? members.fixtureHome : members.fixtureAway}</span>
        <span className="visually-hidden">{match.home ? copy.atHome : copy.away}</span>
      </span>
    </span>
  );
}

/**
 * The weeks ahead as a matrix: a line for each club and a column for each gameweek, so a club's
 * run reads across and a week's opponents read down. A cell is the opponent, its colours and
 * the venue, with a home match filled and an away match outlined as on the member's rail. A
 * double week holds two, a blank week says so, and a match already behind the club stays in
 * its cell in a quieter tone, so that it is not read as a blank week.
 */
export function FixtureMatrix({
  payload,
  weeks,
  copy,
}: {
  payload: FixturesPayload;
  weeks: readonly FixtureGameweek[];
  copy: FixturesCopy;
}) {
  const { messages } = useLanguage();
  return (
    <table className={styles.matrix} data-mark="fixture-matrix">
      <caption className="visually-hidden">{copy.generalView}</caption>
      <thead>
        <tr>
          <th scope="col" className={styles.corner}>
            <span className="visually-hidden">{copy.clubLegend}</span>
          </th>
          {weeks.map((week) => (
            <th key={week.gameweek} scope="col" className={`${styles.week} num`}>
              {messages.common.gameweekShort(week.gameweek)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {clubMatrix(payload, weeks).map(({ club, cells }) => (
          <tr key={club.short_name}>
            <th scope="row" className={styles.club} title={club.name}>
              <span className={styles.clubLabel}>
                <ClubSwatch code={club.short_name} split />
                <span className={styles.clubCode}>{club.short_name}</span>
                <span className={styles.clubName}>{club.name}</span>
              </span>
            </th>
            {cells.map((matches, index) => (
              <td key={weeks[index]!.gameweek} className={styles.cell}>
                {matches.length === 0 ? (
                  <span className={styles.blank}>{messages.leagueMembers.fixtureNone}</span>
                ) : (
                  matches.map((match) => (
                    <Match key={match.fixture.fixture_id} match={match} copy={copy} />
                  ))
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
