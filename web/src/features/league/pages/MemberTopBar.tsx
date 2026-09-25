import { Link } from "react-router";

import { useLanguage } from "../../../i18n/context";
import { deadlineLong, deadlineShort } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { gameweekDeadline } from "../advice/deadline";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { SwitchIcon } from "../components/memberIcons";
import type { EntrySquad, EntryView, LeagueViewEnvelope } from "../types";
import { scoreBugCells, type ScoreCell } from "./scoreBug";
import styles from "./LeagueMemberPage.module.css";

/**
 * The member page's top bar: the team as the page's one heading, the gameweek in broadcast
 * capitals with its deadline, and the score bug.
 *
 * Every cell of the score bug is a published number or arithmetic the league table already
 * does: the rank among the league's members, the season total, last week net of the hits
 * taken (as the member list nets it; with the hit unknown there is no number), the bank and
 * the free transfers. A cell whose number is absent is left out, never shown as 0. The
 * deadline is the fixture calendar's; once it has passed the bar says so and the page's
 * passed-deadline statement explains, and with no calendar the bar says nothing about it.
 */
export function MemberTopBar({
  squad,
  members,
  fixtures,
  deadlinePassed,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  members: EntryView[];
  fixtures: FixturesPayload | null;
  deadlinePassed: string | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = squad.payload;
  const entry = view.entry;
  const deadline = deadlinePassed ?? gameweekDeadline(fixtures, view.season, view.gameweek);
  const humans = members.filter((member) => member.member_kind === "human").length;
  const cells = scoreBugCells(entry, humans, view, locale, copy);
  return (
    <header className={styles.topBar}>
      <div className={styles.topIdentity}>
        <h1 className={styles.teamName}>{entry.team_name ?? copy.unknownTeam}</h1>
        <ExampleDataBadge sourceKind={squad.source_kind} />
      </div>
      <TopWeek gameweek={view.gameweek} deadline={deadline} passed={deadlinePassed !== null} />
      <ScoreBug cells={cells} />
    </header>
  );
}

/**
 * The gameweek in broadcast capitals and its deadline, long on wide screens and short on a
 * phone; with no stated deadline, the week alone.
 */
export function TopWeek({
  gameweek,
  deadline,
  passed,
}: {
  gameweek: number;
  deadline: string | null;
  passed: boolean;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <div className={styles.topWeek}>
      <p className={styles.weekLabel}>{copy.weekLabel(gameweek)}</p>
      {deadline ? (
        <p className={styles.deadline}>
          <span className={styles.deadlineLabel}>
            {passed ? copy.deadlinePassedLabel : copy.deadlineLabel}
          </span>{" "}
          <span className={styles.deadlineLong}>{deadlineLong(deadline, locale)}</span>
          <span className={styles.deadlineShort}>{deadlineShort(deadline, locale)}</span>
        </p>
      ) : null}
    </div>
  );
}

/** The score bug itself: label over figure, the labels in broadcast capitals. */
export function ScoreBug({ cells }: { cells: ScoreCell[] }) {
  return cells.length > 0 ? (
    <dl className={styles.scoreBug}>
      {cells.map((cell) => (
        <div key={cell.key} className={styles.scoreCell}>
          <dt>{cell.label}</dt>
          <dd>{cell.value}</dd>
        </div>
      ))}
    </dl>
  ) : null;
}

/**
 * The sidebar's WHO block: the league, and the member this page is about as a link back
 * to the member list, where another member is picked. The page's address names the member;
 * the visitor's own claim (in memory only) is not read here.
 */
export function MemberWho({
  squad,
  leagueName,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  leagueName?: string;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const entry = squad.payload.entry;
  return (
    <div className={styles.who}>
      <p className={styles.whoLeague}>{leagueName ?? copy.leagueNumber(squad.payload.league_id)}</p>
      <Link to="/league/members" className={styles.whoLink}>
        <span className={styles.whoText}>
          <span className={styles.whoTeam}>{entry.team_name ?? copy.unknownTeam}</span>
          <span className={styles.whoManager}>
            {copy.memberLine(entry.manager_name ?? copy.unknownMember, entry.entry_id)}
          </span>
        </span>
        <SwitchIcon />
        <span className="visually-hidden">{messages.shell.changeMember}</span>
      </Link>
    </div>
  );
}
