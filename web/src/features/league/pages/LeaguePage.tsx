import { Link } from "react-router";

import { useIndex, useLeague, useLedger } from "../../../data/queries";
import type { LeagueView, LedgerRowView, PlayerView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { percent, points, signedPoints, utcShort } from "../../../lib/format";
import { AverageChart } from "../components/AverageChart";
import { CumulativeChart } from "../components/CumulativeChart";
import styles from "./LeaguePage.module.css";

export function LeaguePage() {
  const index = useIndex();
  const season = index.data?.payload.seasons[0];
  const ledger = useLedger(season);
  const league = useLeague(season);
  if (index.isPending || (season && ledger.isPending)) {
    return <EmptyState title="Loading the season…" />;
  }
  if (index.isError || ledger.isError) {
    return (
      <EmptyState title="The ledger could not be read.">
        {String(index.error ?? ledger.error)}
      </EmptyState>
    );
  }
  if (!season || !ledger.data) return <EmptyState title="No season yet." />;
  const view = ledger.data.payload;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>season {view.season}</div>
          <h1 className={styles.title}>League analysis</h1>
          <p className={styles.lede}>
            How this season is going, and how that compares with everyone else playing the same
            game.
          </p>
        </div>
      </header>

      <StatRow>
        <Stat
          label="decided · settled"
          value={`${view.decided_gameweeks} · ${view.settled_gameweeks}`}
          note="gameweeks with a frozen decision · with an outcome"
        />
        <Stat
          label="realized vs projected"
          value={
            view.total_projection_error !== null ? signedPoints(view.total_projection_error) : "—"
          }
          note={
            view.total_realized_score !== null
              ? `${points(view.total_realized_score, 0)} realized on settled weeks`
              : "shown once a gameweek settles"
          }
          tone={view.total_realized_score === null ? "muted" : "default"}
        />
        <Stat
          label="hits · chips"
          value={`${points(view.total_transfer_hit_points, 0)} · ${view.chips_played.length}`}
          note={view.chips_played.length ? view.chips_played.join(", ") : "no chip played yet"}
        />
      </StatRow>

      {view.rows.length > 1 ? (
        <Card title="Projected vs realized, cumulative" aside="points">
          <CumulativeChart rows={view.rows} />
        </Card>
      ) : view.rows.length === 1 ? (
        <Card tone="muted" title="Projected vs realized, cumulative" aside="from gameweek 2">
          <p className={styles.sub}>
            One gameweek is a point, not a line. The chart starts once a second decision exists; the
            realized line starts once the first gameweek settles.
          </p>
        </Card>
      ) : null}

      {league.data ? (
        <AgainstTheLeague view={league.data.payload} />
      ) : (
        <Card tone="muted" title="Against the rest of the league">
          <p className={styles.para}>
            The comparison is built from the capture the decision used; this site build did not
            include one, so nothing about the league is claimed here.
          </p>
        </Card>
      )}

      {view.rows.length === 0 ? (
        <EmptyState title="No decision recorded yet.">
          The first row appears once gameweek 1 is decided.
        </EmptyState>
      ) : (
        <Card title="Our season" aside="each row is a frozen, checksummed ledger entry">
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption className="visually-hidden">Season ledger, one row per gameweek</caption>
              <thead>
                <tr>
                  <th scope="col">GW</th>
                  <th scope="col">decision</th>
                  <th scope="col" className={styles.right}>
                    projected
                  </th>
                  <th scope="col" className={styles.right}>
                    realized
                  </th>
                  <th scope="col" className={styles.right}>
                    error
                  </th>
                  <th scope="col" className={styles.right}>
                    hits
                  </th>
                  <th scope="col">chip</th>
                  <th scope="col">state</th>
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

      <p className={styles.note}>
        Realized points come from the settle step and are never edited by hand; a projection error
        is realized minus projected for the frozen XI (captain counted twice, no automatic
        substitutions).
      </p>
    </div>
  );
}

function AgainstTheLeague({ view }: { view: LeagueView }) {
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
      : `${player?.short_name ?? id} ${percentOwned.toFixed(1)}%`;
  };
  return (
    <>
      <Card
        title="Against the rest of the league"
        aside={`the game's own weekly summary · capture ${view.source_snapshot_id.slice(0, 24)}…`}
      >
        <p className={styles.para}>{view.verdict}</p>
        {view.scored_gameweeks > 0 ? (
          <AverageChart weeks={view.weeks} />
        ) : (
          <p className={styles.sub}>
            The chart starts with the first scored gameweek: the game publishes an average only once
            a gameweek finishes, so there is nothing to draw yet.
          </p>
        )}
      </Card>
      {ownership && (
        <Card
          title="How much of this squad is the template"
          aside={`gameweek ${ownership.gameweek}`}
        >
          <StatRow>
            <Stat
              label="mean starter ownership"
              value={percent(ownership.mean_starter_ownership / 100, 1)}
              note="the average share of the field that owns one of our starters"
            />
            <Stat
              label="effective ownership"
              value={percent(ownership.effective_ownership / 100, 0)}
              note="starters plus the captain again — the exposure we share with the field"
            />
            <Stat
              label="differentials"
              value={`${ownership.differentials.length}`}
              note={`starters owned by ${ownership.differential_threshold_percent}% or less`}
            />
          </StatRow>
          <p className={styles.sub}>
            Most owned: {owned(ownership.most_owned_starter)} · least owned:{" "}
            {owned(ownership.least_owned_starter)}. Ownership is the capture&apos;s
            selected_by_percent at decision time; it moves after the deadline and this page does not
            follow it.
          </p>
        </Card>
      )}
    </>
  );
}

function Row({ row, season }: { row: LedgerRowView; season: string }) {
  return (
    <tr>
      <td className="num">
        <Link to={`/gw/${season}/${row.gameweek}`}>{row.gameweek}</Link>
      </td>
      <td>
        <div>
          {row.decision_kind === "opening"
            ? "Opening squad"
            : `${row.transfer_count} transfer${row.transfer_count === 1 ? "" : "s"}`}
        </div>
        <div className={styles.sub}>
          deadline {utcShort(row.deadline_utc)} · {row.solver_status}
        </div>
      </td>
      <td className={`${styles.right} num`}>{points(row.projected_score)}</td>
      <td className={`${styles.right} num`}>
        {row.realized_score !== null ? points(row.realized_score, 0) : "—"}
      </td>
      <td className={`${styles.right} num`}>
        {row.projection_error !== null ? signedPoints(row.projection_error) : "—"}
      </td>
      <td className={`${styles.right} num`}>{points(row.transfer_hit_points, 0)}</td>
      <td>{row.chip ?? "—"}</td>
      <td>{row.settled ? <Badge tone="good">settled</Badge> : <Badge>decided</Badge>}</td>
    </tr>
  );
}
