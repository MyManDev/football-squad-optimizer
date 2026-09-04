import { Link } from "react-router";

import { useIndex, useLeague, useLedger } from "../../../data/queries";
import type { LeagueView, LedgerRowView, PlayerView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { verdictText } from "../../../i18n/reasons";
import { percent, points, signedPoints, utcShort } from "../../../lib/format";
import { AverageChart } from "../components/AverageChart";
import { CumulativeChart } from "../components/CumulativeChart";
import styles from "./LeaguePage.module.css";

export function LeaguePage() {
  const { locale, messages } = useLanguage();
  const copy = messages.league;
  const index = useIndex();
  const season = index.data?.payload.seasons[0];
  const ledger = useLedger(season);
  const league = useLeague(season);
  if (index.isPending || (season && ledger.isPending)) {
    return <EmptyState title={copy.loading} />;
  }
  if (index.isError || ledger.isError) {
    return <EmptyState title={copy.ledgerError}>{String(index.error ?? ledger.error)}</EmptyState>;
  }
  if (!season || !ledger.data) return <EmptyState title={copy.noSeason} />;
  const view = ledger.data.payload;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {copy.season} {view.season}
          </div>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.lede}>{copy.lede}</p>
        </div>
      </header>

      <StatRow>
        <Stat
          label={copy.decidedSettled}
          value={`${view.decided_gameweeks} · ${view.settled_gameweeks}`}
          note={copy.decidedSettledNote}
        />
        <Stat
          label={copy.realizedProjected}
          value={
            view.total_projection_error !== null
              ? signedPoints(view.total_projection_error, 1, locale)
              : "—"
          }
          note={
            view.total_realized_score !== null
              ? copy.realizedWeeks(points(view.total_realized_score, 0, locale))
              : copy.shownWhenSettled
          }
          tone={view.total_realized_score === null ? "muted" : "default"}
        />
        <Stat
          label={copy.hitsChips}
          value={`${points(view.total_transfer_hit_points, 0, locale)} · ${view.chips_played.length}`}
          note={view.chips_played.length ? view.chips_played.join(", ") : copy.noChip}
        />
      </StatRow>

      <Card
        title={messages.leagueMembers.linkTitle}
        aside={messages.leagueMembers.leagueNumber(352490)}
      >
        <p className={styles.para}>{messages.leagueMembers.linkBody}</p>
        <p className={styles.para}>
          <Link to="/league/members">{messages.leagueMembers.linkLabel}</Link>
        </p>
      </Card>

      {view.rows.length > 1 ? (
        <Card title={copy.cumulative} aside={copy.points}>
          <CumulativeChart rows={view.rows} />
        </Card>
      ) : view.rows.length === 1 ? (
        <Card tone="muted" title={copy.cumulative} aside={copy.fromGw2}>
          <p className={styles.sub}>{copy.onePoint}</p>
        </Card>
      ) : null}

      {league.data ? (
        <AgainstTheLeague view={league.data.payload} />
      ) : (
        <Card tone="muted" title={copy.againstLeague}>
          <p className={styles.para}>{copy.comparisonMissing}</p>
        </Card>
      )}

      {view.rows.length === 0 ? (
        <EmptyState title={messages.common.noDecisionRecorded}>{copy.firstRow}</EmptyState>
      ) : (
        <Card title={copy.ourSeason} aside={copy.ledgerAside}>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className="visually-hidden">{copy.ledgerCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{messages.common.gameweekShort(0).replace("0", "")}</th>
                  <th scope="col">{copy.decision}</th>
                  <th scope="col" className={styles.right}>
                    {copy.projected}
                  </th>
                  <th scope="col" className={styles.right}>
                    {copy.realized}
                  </th>
                  <th scope="col" className={styles.right}>
                    {copy.error}
                  </th>
                  <th scope="col" className={styles.right}>
                    {copy.hits}
                  </th>
                  <th scope="col">{copy.chip}</th>
                  <th scope="col">{copy.state}</th>
                </tr>
              </thead>
              <tbody>
                {view.rows.map((row) => (
                  <Row key={row.gameweek} row={row} season={view.season} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <p className={styles.note}>{copy.note}</p>
    </div>
  );
}

function AgainstTheLeague({ view }: { view: LeagueView }) {
  const { locale, messages } = useLanguage();
  const copy = messages.league;
  const ownership = view.ownership;
  const byId = new Map<number, PlayerView>(
    (ownership?.squad ?? []).map((player) => [player.player_id, player]),
  );
  const owned = (id: number | null): string => {
    if (id === null) return "—";
    const percentOwned = ownership?.ownership_percent[String(id)];
    const player = byId.get(id);
    return percentOwned === undefined
      ? "—"
      : `${player?.short_name ?? id} ${percent(percentOwned / 100, 1, locale)}`;
  };
  return (
    <>
      <Card title={copy.againstLeague} aside={copy.weeklySummary(view.source_snapshot_id)}>
        <p className={styles.para}>
          {verdictText(messages, view.verdict_code, view.verdict_params, view.verdict)}
        </p>
        {view.scored_gameweeks > 0 ? (
          <AverageChart weeks={view.weeks} />
        ) : (
          <p className={styles.sub}>{copy.chartStarts}</p>
        )}
      </Card>
      {ownership && (
        <Card title={copy.templateTitle} aside={copy.gameweekAside(ownership.gameweek)}>
          <StatRow>
            <Stat
              label={copy.meanOwnership}
              value={percent(ownership.mean_starter_ownership / 100, 1, locale)}
              note={copy.meanOwnershipNote}
            />
            <Stat
              label={copy.effectiveOwnership}
              value={percent(ownership.effective_ownership / 100, 0, locale)}
              note={copy.effectiveOwnershipNote}
            />
            <Stat
              label={copy.differentials}
              value={`${ownership.differentials.length}`}
              note={copy.differentialNote(ownership.differential_threshold_percent)}
            />
          </StatRow>
          <p className={styles.sub}>
            {copy.mostOwned}: {owned(ownership.most_owned_starter)} · {copy.leastOwned}:{" "}
            {owned(ownership.least_owned_starter)}. {copy.ownershipNote}
          </p>
        </Card>
      )}
    </>
  );
}

function Row({ row, season }: { row: LedgerRowView; season: string }) {
  const { locale, messages } = useLanguage();
  const copy = messages.league;
  return (
    <tr>
      <td className="num">
        <Link to={`/gw/${season}/${row.gameweek}`}>{row.gameweek}</Link>
      </td>
      <td>
        <div>
          {row.decision_kind === "opening"
            ? copy.openingSquad
            : copy.transferCount(row.transfer_count)}
        </div>
        <div className={styles.sub}>
          {copy.deadline} {utcShort(row.deadline_utc, locale)} · {row.solver_status}
        </div>
      </td>
      <td className={`${styles.right} num`}>{points(row.projected_score, 1, locale)}</td>
      <td className={`${styles.right} num`}>
        {row.realized_score !== null ? points(row.realized_score, 0, locale) : "—"}
      </td>
      <td className={`${styles.right} num`}>
        {row.projection_error !== null ? signedPoints(row.projection_error, 1, locale) : "—"}
      </td>
      <td className={`${styles.right} num`}>{points(row.transfer_hit_points, 0, locale)}</td>
      <td>{row.chip ?? "—"}</td>
      <td>
        {row.settled ? <Badge tone="good">{copy.settled}</Badge> : <Badge>{copy.decided}</Badge>}
      </td>
    </tr>
  );
}
