import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import { gameweekDeadline, useDeadlinePassed } from "../advice/deadline";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import type { ScoreboardState } from "../components/karne";
import { DisclosureIcon } from "../components/memberIcons";
import { SystemKarne } from "../components/SystemKarne";
import { ViewerChips } from "../components/ViewerChips";
import { LeagueDataMissing, loadEntrySquad, loadLeagueMembers, loadScoreboard } from "../data";
import { useViewerEntry } from "../identity/useViewerEntry";
import { follower, gapToLeader, leaderTotal, netWeekPoints } from "../standing";
import type {
  EntrySquad,
  HumanEntryView,
  LeagueMembers,
  LeagueViewEnvelope,
  RankMovement,
} from "../types";
import { ScoreBug, TopWeek } from "./MemberTopBar";
import { scoreBugCells } from "./scoreBug";
import barStyles from "./LeagueMemberPage.module.css";
import styles from "./LeagueMembersPage.module.css";

export function LeagueMembersPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { viewer } = useViewerEntry();
  const query = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
    staleTime: 60_000,
  });
  // The system's record beside the table; the same document /league reads, without the
  // member histories that page also fetches.
  const scoreboard = useQuery({
    queryKey: ["provisional-league-scoreboard"],
    queryFn: loadScoreboard,
    staleTime: 60_000,
    retry: false,
  });
  // The viewer's own squad document, only once the visitor has said who they are: it holds
  // the bank, the free transfers and the chips. The member page shares the read.
  const viewerSquad = useQuery({
    queryKey: ["provisional-entry-squad", viewer?.entryId ?? null],
    queryFn: () => loadEntrySquad(viewer!.entryId),
    enabled: viewer !== null,
    staleTime: 60_000,
    retry: false,
  });
  const fixtures = useFixtures();
  // Re-read once a minute, so an open page notices its deadline passing.
  const deadlinePassed = useDeadlinePassed(
    query.data?.payload.season,
    query.data?.payload.gameweek,
  );
  if (query.isPending) return <EmptyState title={copy.loading} />;
  if (query.isError) {
    const missing = query.error instanceof LeagueDataMissing;
    return (
      <EmptyState title={missing ? copy.notAvailable : copy.membersUnreadable}>
        <p>{missing ? copy.notAvailableBody : copy.membersUnreadableBody}</p>
        {!missing ? (
          <button type="button" onClick={() => void query.refetch()}>
            {copy.retryPublishedRead}
          </button>
        ) : null}
      </EmptyState>
    );
  }
  const scoreboardState: ScoreboardState = scoreboard.isPending
    ? { status: "pending" }
    : scoreboard.isError
      ? { status: scoreboard.error instanceof LeagueDataMissing ? "missing" : "error" }
      : { status: "ready", envelope: scoreboard.data };
  return (
    <LeagueMembersView
      envelope={query.data}
      scoreboard={scoreboardState}
      viewerSquad={viewer !== null ? (viewerSquad.data ?? null) : null}
      fixtures={fixtures.data ?? null}
      deadlinePassed={deadlinePassed !== null}
    />
  );
}

/**
 * The league table, as D-Lig draws it: the gameweek and its deadline in the top bar (with
 * the viewer's score bug once the visitor has said who they are), the table as the page's
 * one focal point, and beside it the system's own record, the viewer's chips and the
 * member right behind the viewer.
 *
 * Every figure is a published one or arithmetic on published ones: the week net of that
 * week's hit, and the gap to the leader's total. An unknown number is a dash, never 0.
 * The system's paper squad is never a row here, and nothing here links to its pages.
 */
export function LeagueMembersView({
  envelope,
  scoreboard,
  viewerSquad = null,
  fixtures = null,
  deadlinePassed = false,
}: {
  envelope: LeagueViewEnvelope<LeagueMembers>;
  /** The system's scoreboard; without it (a page rendered on its own) there is no record. */
  scoreboard?: ScoreboardState;
  /** The viewer's own squad document, for the bank, the free transfers and the chips. */
  viewerSquad?: LeagueViewEnvelope<EntrySquad> | null;
  fixtures?: FixturesPayload | null;
  /** The calendar's deadline for this gameweek has passed. */
  deadlinePassed?: boolean;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { viewer, select, clear } = useViewerEntry();
  const navigate = useNavigate();
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
  const deadline = gameweekDeadline(fixtures, view.season, view.gameweek);
  const cells = viewerRow ? scoreBugCells(viewerRow, rows.length, squad, locale, copy) : [];
  const count = (value: number) => points(value, 0, locale);

  return (
    <div className={styles.page}>
      <header className={barStyles.topBar}>
        <TopWeek gameweek={view.gameweek} deadline={deadline} passed={deadlinePassed} />
        <ExampleDataBadge sourceKind={envelope.source_kind} />
        <ScoreBug cells={cells} />
      </header>

      <div className={styles.columns}>
        <section className={styles.tableColumn} aria-labelledby="league-table-title">
          <div className={styles.heading}>
            <h1 className={styles.title} id="league-table-title">
              {copy.title}
            </h1>
            <p className={styles.context}>
              <span>{view.league_name}</span>
              <span>{copy.memberCount(rows.length)}</span>
              {view.scored_gameweek !== null ? (
                <span>{copy.afterGameweek(view.scored_gameweek)}</span>
              ) : null}
            </p>
          </div>

          <div className={styles.viewer}>
            {viewer === null ? (
              <p className={styles.viewerLine}>
                <strong>{copy.viewerTitle}</strong> {copy.viewerPrompt}
              </p>
            ) : (
              <p className={styles.viewerLine}>
                {viewerRow ? (
                  <>
                    <strong>
                      {copy.viewerSelected(viewerRow.manager_name ?? `#${viewerRow.entry_id}`)}
                    </strong>{" "}
                    <Link
                      className={styles.viewerAction}
                      to={`/league/members/${viewerRow.entry_id}`}
                    >
                      {copy.viewerOpenMine}
                    </Link>
                  </>
                ) : (
                  <>{copy.viewerMissing}</>
                )}{" "}
                <a className={styles.viewerAction} href="#league-member-list">
                  {copy.viewerChange}
                </a>{" "}
                <button type="button" className={styles.viewerClear} onClick={clear}>
                  {copy.viewerClear}
                </button>
              </p>
            )}
          </div>

          <table
            id="league-member-list"
            className={styles.table}
            data-viewer={viewerRow ? "" : undefined}
          >
            <caption className="visually-hidden">{copy.caption(view.league_name)}</caption>
            <thead>
              <tr>
                <th scope="col" className={styles.rank}>
                  {copy.rank}
                </th>
                <th scope="col" className={styles.move}>
                  <span className="visually-hidden">{copy.movement}</span>
                </th>
                <th scope="col" className={styles.team}>
                  {copy.team}
                </th>
                <th scope="col" className={styles.week}>
                  <span aria-hidden="true">{copy.lastWeekLabel}</span>
                  {/* The view is labelled with the coming gameweek; the scores are an earlier
                      one's, and net of that week's hits. The header says which, in full. */}
                  <span className="visually-hidden">
                    {view.scored_gameweek === null
                      ? copy.gameweekNetPoints
                      : copy.gameweekNetPointsFor(view.scored_gameweek)}
                  </span>
                </th>
                <th scope="col" className={styles.total}>
                  {copy.total}
                </th>
                <th scope="col" className={styles.gap}>
                  {copy.leaderGap}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((member) => {
                const isViewer = member === viewerRow;
                const net = netWeekPoints(member);
                const gap = gapToLeader(lead, member);
                return (
                  <tr
                    key={member.entry_id}
                    className={isViewer ? styles.viewerRow : undefined}
                    aria-current={isViewer ? "true" : undefined}
                  >
                    <td className={styles.rank}>{member.rank > 0 ? member.rank : "—"}</td>
                    <td className={styles.move}>
                      <Movement movement={member.movement} places={member.movement_places} />
                    </td>
                    <td className={styles.team}>
                      <div className={styles.teamCell}>
                        <span className={styles.teamName}>
                          {member.team_name ?? copy.unknownTeam}
                        </span>
                        <span className={styles.manager}>
                          <Link
                            className={styles.memberLink}
                            to={`/league/members/${member.entry_id}`}
                          >
                            {member.manager_name ?? copy.unknownMember}
                          </Link>
                          {isViewer ? <span> · {copy.viewerYouBadge}</span> : null}
                        </span>
                        {isViewer ? null : (
                          <button
                            type="button"
                            className={styles.viewerSelect}
                            onClick={() => {
                              select(member.entry_id);
                              navigate(`/league/members/${member.entry_id}`);
                            }}
                          >
                            {copy.viewerSelect}
                          </button>
                        )}
                      </div>
                    </td>
                    <td className={`${styles.week} num`}>{net === null ? "—" : count(net)}</td>
                    <td className={`${styles.total} num`}>
                      {member.total_points === null ? "—" : count(member.total_points)}
                    </td>
                    <td className={`${styles.gap} num`}>
                      {gap === null ? (
                        "—"
                      ) : gap === 0 ? (
                        <span className={styles.leader}>{copy.leaderMark}</span>
                      ) : (
                        count(gap)
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Without a finished week the columns are dashes, and the page says why. */}
          {view.scored_gameweek === null ? (
            <p className={styles.note}>{copy.noScoredWeek}</p>
          ) : null}

          <details className={styles.about}>
            <summary className={styles.aboutSummary}>
              <DisclosureIcon className={styles.aboutIcon} />
              <span>{copy.aboutTable}</span>
            </summary>
            <div className={styles.aboutBody}>
              <h2 className={styles.aboutTitle}>{copy.publicDataTitle}</h2>
              <p>{copy.publicDataBody}</p>
              <p>{copy.viewerBody}</p>
              <p>{copy.movementNote}</p>
              {/* The column is netted for every row, so the basis belongs to the column, and
                  it differs from what the FPL site shows a manager. */}
              {view.scored_gameweek !== null ? <p>{copy.gameweekNetNote}</p> : null}
            </div>
          </details>
        </section>

        {scoreboard || squad || chaser ? (
          <div className={styles.side}>
            {scoreboard ? <SystemKarne state={scoreboard} leagueId={view.league_id} /> : null}
            {squad ? <ViewerChips squad={squad} /> : null}
            {chaser ? (
              <p className={styles.chaser}>
                {copy.followerLabel}{" "}
                <strong>
                  {chaser.member.manager_name ??
                    chaser.member.team_name ??
                    `#${chaser.member.entry_id}`}
                </strong>
                ,{" "}
                {chaser.behind === null
                  ? null
                  : chaser.behind === 0
                    ? copy.followerLevel
                    : copy.followerBehind(count(chaser.behind))}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The movement cell: an arrow and the places moved, '=' for no change, the words for
 * anything else. The glyphs are for the eye; a screen reader hears the words, which also
 * keep an unknown previous rank apart from an unchanged one.
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
          : copy.noPreviousRank;
  return (
    <>
      <span className={styles.moveMark} aria-hidden="true" data-movement={movement}>
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
      <span className="visually-hidden">{words}</span>
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
