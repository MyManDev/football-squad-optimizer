import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useIndex, useLedger } from "../../../data/queries";
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
  const index = useIndex();
  const query = useQuery({
    queryKey: ["provisional-league-members"],
    queryFn: loadLeagueMembers,
    staleTime: 60_000,
  });
  // Our row's week must match the week the published members are scored in, so it is read
  // after the members document rather than beside it.
  const scored = query.data?.payload.scored_gameweek ?? null;
  const systemRow = useSystemRow(index.data?.payload.seasons[0], scored);

  if (query.isPending) return <EmptyState title={copy.loading} />;
  if (query.isError) {
    return <EmptyState title={copy.notAvailable}>{copy.notAvailableBody}</EmptyState>;
  }
  return <LeagueMembersView envelope={query.data} systemRow={systemRow} />;
}

/**
 * Our own row, read from the ledger the site already publishes.
 *
 * The producer deliberately does not write it: a member's advice must be computed without
 * reference to our squad, so the module that renders members never reads our ledger. That
 * leaves the site to add the row from its own record — which is also the only place the
 * number is settled rather than projected.
 *
 * No rank is claimed. Placing ourselves among the members needs their points, and the
 * standings view does not carry them; a rank invented here would be the one number on the
 * page that nobody measured.
 */
function useSystemRow(season: string | undefined, scoredGameweek: number | null): EntryView | null {
  const ledger = useLedger(season);
  const payload = ledger.data?.payload;
  if (!payload || payload.settled_gameweeks === 0) return null;
  const settled = payload.rows.filter((row) => row.settled && row.realized_net_score !== null);
  // Our score and theirs share one column under one heading. If our latest settled week is
  // not the week that heading names, the two numbers describe different weeks, so ours is
  // withheld rather than shown beside a label it does not belong to.
  const latest =
    scoredGameweek === null
      ? null
      : (settled.find((row) => row.gameweek === scoredGameweek) ?? null);
  return {
    member_kind: "system",
    entry_id: null,
    manager_name: "SquadOpt",
    team_name: "SquadOpt",
    rank: 0,
    // Gross week plus the hit, the same two numbers every member's row carries, so the
    // column nets all of them the same way instead of netting ours somewhere else.
    gameweek_points: latest?.realized_score ?? null,
    transfer_cost: latest?.transfer_hit_points ?? null,
    total_points: latest === null ? null : payload.total_realized_net_score,
    movement: "unknown",
    movement_places: null,
    data_quality: "complete",
  };
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

export function LeagueMembersView({
  envelope,
  systemRow = null,
}: {
  envelope: LeagueViewEnvelope<LeagueMembers>;
  systemRow?: EntryView | null;
}) {
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
  // The example envelope carries its own system row; a live one never does, because the
  // producer must not read our ledger. Appending unconditionally would double it.
  const alreadyPresent = view.members.some((member) => member.member_kind === "system");
  const rows: EntryView[] =
    systemRow && !alreadyPresent ? [...view.members, systemRow] : view.members;
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

      <Card title={copy.members} aside={copy.memberCount(view.members.length)}>
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
                  key={member.member_kind === "system" ? "squadopt" : member.entry_id}
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
        {rows.some((member) => member.member_kind === "system") && (
          <p className={styles.notice}>{messages.league.note}</p>
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
