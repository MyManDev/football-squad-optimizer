import { useLanguage } from "../../../i18n/context";
import { deadlineLong, deadlineShort } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { gameweekDeadline, minutesLeft } from "../advice/deadline";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
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
 * While it is open, the page's minute clock counts down to it.
 */
export function MemberTopBar({
  squad,
  members,
  fixtures,
  deadlinePassed,
  now,
}: {
  squad: LeagueViewEnvelope<EntrySquad>;
  members: EntryView[];
  fixtures: FixturesPayload | null;
  deadlinePassed: string | null;
  now?: number;
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
      <TopWeek
        gameweek={view.gameweek}
        deadline={deadline}
        passed={deadlinePassed !== null}
        now={now}
      />
      <ScoreBug cells={cells} />
    </header>
  );
}

type CountdownUnits = ReturnType<typeof useLanguage>["messages"]["leagueMembers"]["countdownUnits"];

/** Minutes left in their largest unit and the next, dropped at zero: "2 gün 14 sa", "3 sa". */
function timeLeft(minutes: number, units: CountdownUnits): string {
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const rest = minutes % 60;
  const pair = (big: number, bigUnit: string, small: number, smallUnit: string) =>
    small > 0 ? `${big} ${bigUnit} ${small} ${smallUnit}` : `${big} ${bigUnit}`;
  if (days > 0) return pair(days, units.day, hours, units.hour);
  if (hours > 0) return pair(hours, units.hour, rest, units.minute);
  return minutes > 0 ? `${minutes} ${units.minute}` : units.underMinute;
}

/**
 * The gameweek in broadcast capitals and its deadline, long on wide screens and short on a
 * phone; with no stated deadline, the week alone. Given the page's clock, an open deadline
 * also shows the time left, rounded down to the minute: it changes once a minute, so it is
 * not a live region (a reader hears it where they reach it, not every minute), and in the
 * last hour it takes the warning tone. On a phone it stands in for the label and the date.
 */
export function TopWeek({
  gameweek,
  deadline,
  passed,
  now,
}: {
  gameweek: number;
  deadline: string | null;
  passed: boolean;
  now?: number;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const left = deadline && !passed && now !== undefined ? minutesLeft(deadline, now) : null;
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
      {deadline && left !== null ? (
        <time
          className={styles.countdown}
          dateTime={deadline}
          data-urgent={left < 60 ? "" : undefined}
          data-testid="deadline-countdown"
        >
          {copy.deadlineLeft(timeLeft(left, copy.countdownUnits))}
        </time>
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
