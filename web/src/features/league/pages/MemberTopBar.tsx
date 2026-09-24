import { Link } from "react-router";

import { useLanguage } from "../../../i18n/context";
import { deadlineLong, deadlineShort, money } from "../../../lib/format";
import type { FixturesPayload } from "../../fixtures/types";
import { gameweekDeadline } from "../advice/deadline";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { SwitchIcon } from "../components/memberIcons";
import { netWeekPoints } from "../standing";
import type { EntrySquad, EntryView, LeagueViewEnvelope } from "../types";
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
  const count = (value: number) => new Intl.NumberFormat(locale).format(value);
  const net = netWeekPoints(entry);
  const cells = [
    Number.isSafeInteger(entry.rank) && entry.rank > 0
      ? {
          key: "rank",
          label: copy.rankLabel,
          value: humans >= entry.rank ? `${entry.rank}/${humans}` : String(entry.rank),
        }
      : null,
    typeof entry.total_points === "number" && Number.isFinite(entry.total_points)
      ? { key: "points", label: copy.pointsLabel, value: count(entry.total_points) }
      : null,
    net !== null && Number.isFinite(net)
      ? { key: "week", label: copy.lastWeekLabel, value: count(net) }
      : null,
    Number.isFinite(view.bank_tenths)
      ? { key: "bank", label: copy.bankLabel, value: money(view.bank_tenths, locale) }
      : null,
    view.free_transfers_known === true &&
    Number.isSafeInteger(view.free_transfers) &&
    view.free_transfers >= 0
      ? { key: "free", label: copy.freeTransfersLabel, value: count(view.free_transfers) }
      : null,
  ].filter((cell) => cell !== null);
  return (
    <header className={styles.topBar}>
      <div className={styles.topIdentity}>
        <h1 className={styles.teamName}>{entry.team_name ?? copy.unknownTeam}</h1>
        <ExampleDataBadge sourceKind={squad.source_kind} />
      </div>
      <div className={styles.topWeek}>
        <p className={styles.weekLabel}>{copy.weekLabel(view.gameweek)}</p>
        {deadline ? (
          <p className={styles.deadline}>
            <span className={styles.deadlineLabel}>
              {deadlinePassed ? copy.deadlinePassedLabel : copy.deadlineLabel}
            </span>{" "}
            <span className={styles.deadlineLong}>{deadlineLong(deadline, locale)}</span>
            <span className={styles.deadlineShort}>{deadlineShort(deadline, locale)}</span>
          </p>
        ) : null}
      </div>
      {cells.length > 0 ? (
        <dl className={styles.scoreBug}>
          {cells.map((cell) => (
            <div key={cell.key} className={styles.scoreCell}>
              <dt>{cell.label}</dt>
              <dd>{cell.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </header>
  );
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
