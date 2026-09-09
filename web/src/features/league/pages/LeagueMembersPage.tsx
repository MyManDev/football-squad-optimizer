import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { loadLeagueMembers } from "../data";
import { useViewerEntry } from "../identity/useViewerEntry";
import type { EntryView, LeagueMembers, LeagueViewEnvelope } from "../types";
import styles from "./LeagueMembersPage.module.css";

export function LeagueMembersPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const query = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
    staleTime: 60_000,
  });
  if (query.isPending) return <EmptyState title={copy.loading} />;
  if (query.isError) {
    return <EmptyState title={copy.notAvailable}>{copy.notAvailableBody}</EmptyState>;
  }
  return <LeagueMembersView envelope={query.data} />;
}

/**
 * The week on the column's one basis: the score after the transfer hits taken that week.
 *
 * That is the number the league total actually advances by — the source's own arithmetic
 * has `total_points` move by `points` minus `event_transfers_cost` — so it is the only
 * basis on which our row and a member's row are the same measurement.
 *
 * Both halves must be known. A missing hit is not a hit of zero: the producer publishes
 * null when nothing proves one, and a row like that shows no week rather than its gross
 * score under a heading that says net.
 */
function netWeekPoints(member: EntryView): number | null {
  const gross = member.gameweek_points;
  const cost = member.transfer_cost;
  if (gross === null || typeof cost !== "number") return null;
  return gross - cost;
}

export function LeagueMembersView({ envelope }: { envelope: LeagueViewEnvelope<LeagueMembers> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const { viewer, select, clear } = useViewerEntry();
  const view = envelope.payload;
  const viewerRow =
    viewer === null
      ? null
      : (view.members.find(
          (member) => member.member_kind === "human" && member.entry_id === viewer.entryId,
        ) ?? null);
  // A published example can include our virtual team; the visitor list is for members.
  const rows = view.members.filter((member) => member.member_kind === "human");
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {view.season} · {messages.common.gameweek(view.gameweek)} ·{" "}
            {copy.leagueNumber(view.league_id)}
          </div>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.lede}>{view.league_name}</p>
        </div>
        <ExampleDataBadge sourceKind={envelope.source_kind} />
      </header>

      <Card tone="muted" title={copy.publicDataTitle}>
        <p className={styles.notice}>{copy.publicDataBody}</p>
      </Card>

      <Card tone="muted" title={copy.viewerTitle}>
        <p className={styles.notice}>{copy.viewerBody}</p>
        {viewerRow ? (
          <p className={styles.notice}>
            <strong>
              {copy.viewerSelected(viewerRow.manager_name ?? `#${viewerRow.entry_id}`)}
            </strong>{" "}
            <Link to={`/league/members/${viewerRow.entry_id}`}>{copy.viewerOpenMine}</Link>{" "}
            <button type="button" className={styles.viewerClear} onClick={clear}>
              {copy.viewerClear}
            </button>
          </p>
        ) : null}
      </Card>

      <Card title={copy.members} aside={copy.memberCount(rows.length)}>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className="visually-hidden">{copy.caption(view.league_name)}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.rank}</th>
                <th scope="col">{copy.member}</th>
                <th scope="col">{copy.team}</th>
                <th scope="col" className={styles.right}>
                  {view.scored_gameweek === null
                    ? copy.gameweekNetPoints
                    : copy.gameweekNetPointsFor(view.scored_gameweek)}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.total}
                </th>
                <th scope="col">{copy.movement}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((member) => (
                <MemberRow
                  key={member.entry_id}
                  member={member}
                  locale={locale}
                  viewerEntryId={viewer?.entryId ?? null}
                  onSelectViewer={select}
                />
              ))}
            </tbody>
          </table>
        </div>
        {view.scored_gameweek === null ? (
          <p className={styles.notice}>{copy.noScoredWeek}</p>
        ) : (
          /* The column is netted for every row, ours included, so the basis belongs to
             the column rather than to our presence in it — and it differs from what the
             FPL site shows a manager, which is the surprise the note exists to remove. */
          <p className={styles.notice}>{copy.gameweekNetNote}</p>
        )}
      </Card>
    </div>
  );
}

function MemberRow({
  member,
  locale,
  viewerEntryId,
  onSelectViewer,
}: {
  member: EntryView;
  locale: string;
  viewerEntryId: number | null;
  onSelectViewer: (entryId: number) => void;
}) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const isViewer = member.member_kind === "human" && member.entry_id === viewerEntryId;
  const net = netWeekPoints(member);
  const movement =
    member.movement === "unknown"
      ? copy.unknown
      : member.movement === "new"
        ? copy.newMember
        : copy.movementLabel(member.movement, member.movement_places ?? 0);
  return (
    <tr className={member.member_kind === "system" ? styles.systemRow : undefined}>
      <td className="num">{member.rank === 0 ? "—" : member.rank}</td>
      <td>
        <Link
          className={styles.memberLink}
          to={
            member.member_kind === "system"
              ? "/league/members/squadopt"
              : `/league/members/${member.entry_id}`
          }
        >
          {member.manager_name ?? copy.unknownMember}
        </Link>
        {member.member_kind === "system" ? (
          <Badge tone="accent">
            <span aria-hidden="true">◈</span> {copy.systemTeamBadge}
          </Badge>
        ) : (
          <span className={styles.sub}>#{member.entry_id}</span>
        )}
        {member.member_kind === "human" ? (
          isViewer ? (
            <Badge tone="accent">{copy.viewerYouBadge}</Badge>
          ) : (
            <button
              type="button"
              className={styles.viewerSelect}
              onClick={() => onSelectViewer(member.entry_id ?? 0)}
            >
              {copy.viewerSelect}
            </button>
          )
        ) : null}
      </td>
      <td>{member.team_name ?? "—"}</td>
      <td className={`${styles.right} num`}>{net === null ? "—" : points(net, 0, locale)}</td>
      <td className={`${styles.right} num`}>
        {member.total_points === null ? "—" : points(member.total_points, 0, locale)}
      </td>
      <td>{movement}</td>
    </tr>
  );
}
