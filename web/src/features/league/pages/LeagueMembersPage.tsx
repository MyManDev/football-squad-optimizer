import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { points } from "../../../lib/format";
import { ExampleDataBadge } from "../components/ExampleDataBadge";
import { loadLeagueMembers } from "../data";
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

export function LeagueMembersView({ envelope }: { envelope: LeagueViewEnvelope<LeagueMembers> }) {
  const { locale, messages } = useLanguage();
  const copy = messages.leagueMembers;
  const view = envelope.payload;
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
                  {copy.gameweekPoints}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.total}
                </th>
                <th scope="col">{copy.movement}</th>
              </tr>
            </thead>
            <tbody>
              {view.members.map((member) => (
                <MemberRow
                  key={member.member_kind === "system" ? "squadopt" : member.entry_id}
                  member={member}
                  locale={locale}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function MemberRow({ member, locale }: { member: EntryView; locale: string }) {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const movement =
    member.movement === "unknown"
      ? copy.unknown
      : member.movement === "new"
        ? copy.newMember
        : copy.movementLabel(member.movement, member.movement_places ?? 0);
  return (
    <tr className={member.member_kind === "system" ? styles.systemRow : undefined}>
      <td className="num">{member.rank}</td>
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
      </td>
      <td>{member.team_name ?? "—"}</td>
      <td className={`${styles.right} num`}>
        {member.gameweek_points === null ? "—" : points(member.gameweek_points, 0, locale)}
      </td>
      <td className={`${styles.right} num`}>
        {member.total_points === null ? "—" : points(member.total_points, 0, locale)}
      </td>
      <td>{movement}</td>
    </tr>
  );
}
