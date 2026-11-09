import { memberAddress } from "../../../lib/leagueAddresses";
import { useLeagueId } from "../useLeague";
import { Link } from "react-router";
import { Fragment, type CSSProperties } from "react";

import { EmptyState } from "../../../design/components/EmptyState";
import { useShellLayout } from "../../../design/shell/layout";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { gameweekDeadline, useDeadlinePassed } from "../advice/deadline";
import { viewerChipLines } from "../chipShape";
import { RowDetailsFigures, RowDetailsToggle } from "../components/RowDetails";
import { useOpenRows } from "../components/useOpenRows";
import { ViewerChips } from "../components/ViewerChips";
import { leagueRace } from "../race/leagueRace";
import { LeagueRaceCard } from "../race/LeagueRaceCard";
import { LeagueDataMissing } from "../data";
import { useLeagueIdentity } from "../identity/useLeagueIdentity";
import { useEntrySquad, useLeagueMembers, useLeagueScoreboard } from "../queries";
import { follower, gapToLeader, leaderTotal, netWeekPoints } from "../standing";
import type {
  EntrySquad,
  HumanEntryView,
  LeagueMembers,
  LeagueViewEnvelope,
  RankMovement,
  Scoreboard,
} from "../types";
import { ScoreBug, TopWeek } from "./MemberTopBar";
import { scoreBugCells } from "./scoreBug";
import barStyles from "./LeagueMemberPage.module.css";
import styles from "./LeagueMembersPage.module.css";

export function LeagueMembersPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const viewer = useLeagueIdentity(useLeagueId()).member;
  const query = useLeagueMembers();
  // The viewer's own squad document, only once the visitor has said who they are: it holds
  // the bank, the free transfers and the chips. The member page shares the read.
  const viewerSquad = useEntrySquad(viewer?.entryId, viewer !== null);
  const fixtures = useFixtures();
  // The scoreboard the league race is drawn from; a missing or failed read draws no race.
  const scoreboard = useLeagueScoreboard();
  // Re-read once a minute, so an open page notices its deadline passing.
  const deadlinePassed = useDeadlinePassed(
    query.data?.payload.season,
    query.data?.payload.gameweek,
  );
  if (query.isPending) return <EmptyState title={copy.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState page title={missing ? copy.notAvailable : copy.membersUnreadable}>
        {!missing ? (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retryPublishedRead}
          </button>
        ) : null}
      </EmptyState>
    );
  }
  return (
    <LeagueMembersView
      envelope={query.data}
      viewerSquad={viewer !== null ? (viewerSquad.data ?? null) : null}
      viewerSquadPending={viewer !== null && viewerSquad.isPending}
      fixtures={fixtures.data ?? null}
      deadlinePassed={deadlinePassed !== null}
      scoreboard={scoreboard.isError ? null : (scoreboard.data?.payload ?? null)}
    />
  );
}

/**
 * The league table, as D-Lig draws it: the gameweek and its deadline in the top bar (with
 * the viewer's score bug), the league's name over the table as the page's one focal point,
 * and beside it the viewer's chips and the member right behind the viewer.
 *
 * Every figure is a published one or arithmetic on published ones: the week net of that
 * week's hit, and the gap to the leader's total. An unknown number is a dash, never 0.
 * The system's paper squad is never a row here, and nothing here links to it.
 *
 * On a phone a row carries what a member looks for first: rank, movement, the team and the
 * manager, and the total. The week's net and the gap to the leader fold out under the row
 * from a chevron at its end, so no column shrinks its figures to fit the screen.
 */
export function LeagueMembersView({
  envelope,
  viewerSquad = null,
  viewerSquadPending = false,
  fixtures = null,
  deadlinePassed = false,
  scoreboard = null,
}: {
  envelope: LeagueViewEnvelope<LeagueMembers>;
  /** The published scoreboard the league race is drawn from; none, no race. */
  scoreboard?: Scoreboard | null;
  /** The viewer's own squad document, for the bank, the free transfers and the chips. */
  viewerSquad?: LeagueViewEnvelope<EntrySquad> | null;
  /** That document is still being read, so its chips may yet land beside the table. */
  viewerSquadPending?: boolean;
  fixtures?: FixturesPayload | null;
  /** The calendar's deadline for this gameweek has passed. */
  deadlinePassed?: boolean;
}) {
  const { locale, messages } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.leagueMembers;
  const viewer = useLeagueIdentity(leagueId).member;
  const view = envelope.payload;
  // A published example can include our virtual team; the visitor list is for members.
  const rows = view.members.filter(
    (member): member is HumanEntryView => member.member_kind === "human",
  );
  const viewerRow =
    viewer === null ? null : (rows.find((member) => member.entry_id === viewer.entryId) ?? null);
  const lead = leaderTotal(rows);
  const chaser = viewerRow ? follower(rows, viewerRow) : null;
  const squad =
    viewerRow && viewerSquad?.payload.entry.entry_id === viewerRow.entry_id
      ? viewerSquad.payload
      : null;
  const chips = squad ? viewerChipLines(squad) : null;
  const deadline = gameweekDeadline(fixtures, view.season, view.gameweek);
  const cells = viewerRow ? scoreBugCells(viewerRow, rows.length, squad, locale, copy) : [];
  const count = (value: number) => points(value, 0, locale);
  const race =
    scoreboard !== null ? leagueRace(scoreboard, view.members, view.scored_gameweek) : null;
  const phone = useShellLayout() === "phone";
  // Only a phone draws the fold.
  const fold = useOpenRows();
  // The header the week's figures stand under, in full: the view is labelled with the
  // coming gameweek, the scores are an earlier one's, and net of that week's hits.
  const weekHeading =
    view.scored_gameweek === null
      ? copy.gameweekNetPoints
      : copy.gameweekNetPointsFor(view.scored_gameweek);

  return (
    <div className={styles.page}>
      <header className={barStyles.topBar}>
        <TopWeek gameweek={view.gameweek} deadline={deadline} passed={deadlinePassed} />
        <ScoreBug cells={cells} />
      </header>

      <div className={styles.columns}>
        <section className={styles.tableColumn} aria-labelledby="league-table-title">
          <h1 className={styles.title} id="league-table-title">
            {view.league_name}
          </h1>

          <table id="league-member-list" className={styles.table}>
            <caption className="visually-hidden">{copy.caption(view.league_name)}</caption>
            <thead>
              <tr>
                <th scope="col" className={styles.rank}>
                  {copy.rank}
                </th>
                <th scope="col" className={styles.move}>
                  <span className="visually-hidden">{copy.movement}</span>
                </th>
                <th scope="col">{copy.team}</th>
                {phone ? null : (
                  <th scope="col" className={styles.week}>
                    <span aria-hidden="true">{copy.lastWeekLabel}</span>
                    <span className="visually-hidden">{weekHeading}</span>
                  </th>
                )}
                <th scope="col" className={styles.total}>
                  {copy.total}
                </th>
                {phone ? (
                  <th scope="col" className={styles.details}>
                    <span className="visually-hidden">{copy.storyDetail}</span>
                  </th>
                ) : (
                  <th scope="col" className={styles.gap}>
                    {copy.leaderGap}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((member, index) => {
                const isViewer = member === viewerRow;
                const net = netWeekPoints(member);
                const gap = gapToLeader(lead, member);
                const open = phone && fold.isOpen(member.entry_id!);
                const detailsId = `league-member-${member.entry_id}-details`;
                const gapCell =
                  gap === null ? (
                    "—"
                  ) : gap === 0 ? (
                    <span className={styles.leader}>{copy.leaderMark}</span>
                  ) : (
                    count(gap)
                  );
                return (
                  <Fragment key={member.entry_id}>
                    <tr
                      className={isViewer ? styles.viewerRow : undefined}
                      style={{ "--row": index } as CSSProperties}
                      aria-current={isViewer ? "true" : undefined}
                    >
                      <td className={styles.rank}>{member.rank > 0 ? member.rank : "—"}</td>
                      <td className={styles.move}>
                        <Movement movement={member.movement} places={member.movement_places} />
                      </td>
                      <td className={styles.teamColumn}>
                        <div className={styles.teamCell}>
                          <span className={styles.teamName}>
                            {member.team_name ?? copy.unknownTeam}
                          </span>
                          <span className={styles.manager}>
                            <Link
                              className={styles.memberLink}
                              to={memberAddress(leagueId, member.entry_id!)}
                            >
                              {member.manager_name ?? copy.unknownMember}
                            </Link>
                            {isViewer ? <span> · {copy.viewerYouBadge}</span> : null}
                          </span>
                        </div>
                      </td>
                      {phone ? null : (
                        <td className={`${styles.week} num`}>{net === null ? "—" : count(net)}</td>
                      )}
                      <td className={`${styles.total} num`}>
                        {member.total_points === null ? "—" : count(member.total_points)}
                      </td>
                      {phone ? (
                        <td className={styles.details}>
                          <RowDetailsToggle
                            open={open}
                            controls={detailsId}
                            label={`${copy.storyDetail}, ${member.team_name ?? copy.unknownTeam}`}
                            onToggle={() => fold.toggle(member.entry_id!)}
                          />
                        </td>
                      ) : (
                        <td className={`${styles.gap} num`}>{gapCell}</td>
                      )}
                    </tr>
                    {open ? (
                      <tr
                        id={detailsId}
                        className={`${styles.detailRow} ${isViewer ? styles.viewerRow : ""}`}
                      >
                        <td colSpan={5}>
                          <RowDetailsFigures
                            figures={[
                              { label: weekHeading, value: net === null ? "—" : count(net) },
                              { label: copy.leaderGap, value: gapCell },
                            ]}
                          />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </section>

        {/* It stands empty during the read, so the table does not narrow when the chips land. */}
        {chips || chaser || viewerSquadPending ? (
          <div className={styles.side}>
            {chips ? <ViewerChips chips={chips} /> : null}
            {chaser ? (
              <p className={styles.chaser}>
                {copy.followerLabel}{" "}
                <strong>
                  {chaser.member.manager_name ?? chaser.member.team_name ?? copy.unknownMember}
                </strong>
                {/* Without both totals there is no distance to state, only the name. */}
                {chaser.behind === null ? (
                  "."
                ) : (
                  <>
                    ,{" "}
                    {chaser.behind === 0
                      ? copy.followerLevel
                      : copy.followerBehind(count(chaser.behind))}
                  </>
                )}
              </p>
            ) : null}
          </div>
        ) : null}

        {/* The league race, from the scoreboard the page reads for it, across both columns. */}
        {race ? (
          <div className={styles.race}>
            <LeagueRaceCard
              race={race}
              members={view.members}
              initialEntry={viewerRow?.entry_id ?? null}
              viewer={viewerRow?.entry_id ?? null}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The movement cell: an arrow and the places moved, '=' for no change, the word for a new
 * member, a dash for anything else. The glyphs are for the eye and a screen reader hears
 * the words; the dash it hears as it is, like the table's other unknown figures.
 */
function Movement({ movement, places }: { movement: RankMovement; places: number | null }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  // Up or down only with a positive whole number of places; anything else is not a count.
  const counted =
    (movement === "up" || movement === "down") &&
    typeof places === "number" &&
    Number.isSafeInteger(places) &&
    places > 0
      ? { direction: movement, places }
      : null;
  const words =
    movement === "new"
      ? copy.newMember
      : movement === "same" && places === 0
        ? copy.movementLabel("same", 0)
        : counted
          ? copy.movementLabel(counted.direction, counted.places)
          : null;
  return (
    <>
      <span
        className={styles.moveMark}
        aria-hidden={words === null ? undefined : "true"}
        data-movement={movement}
      >
        {counted ? (
          <>
            <MoveArrow direction={counted.direction} />
            {counted.places}
          </>
        ) : movement === "same" && places === 0 ? (
          "="
        ) : movement === "new" ? (
          copy.newMember
        ) : (
          "—"
        )}
      </span>
      {words === null ? null : <span className="visually-hidden">{words}</span>}
    </>
  );
}

function MoveArrow({ direction }: { direction: "up" | "down" }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="square"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={direction === "up" ? "M6 10.5V2M2.5 5.5L6 2l3.5 3.5" : "M6 1.5V10M2.5 6.5L6 10l3.5-3.5"}
      />
    </svg>
  );
}
