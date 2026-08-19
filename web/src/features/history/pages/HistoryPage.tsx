import { Link } from "react-router";

import { useIndex, useLedger } from "../../../data/queries";
import type { LedgerRowView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { points, signedPoints, utcShort } from "../../../lib/format";
import styles from "./HistoryPage.module.css";

export function HistoryPage() {
  const index = useIndex();
  const season = index.data?.payload.seasons[0];
  const ledger = useLedger(season);
  if (index.isPending || (season && ledger.isPending)) {
    return <EmptyState title="Loading the season ledger…" />;
  }
  if (index.isError || ledger.isError) {
    return (
      <EmptyState title="The ledger could not be read.">
        {String(index.error ?? ledger.error)}
      </EmptyState>
    );
  }
  if (!season || !ledger.data) {
    return <EmptyState title="No season yet." />;
  }
  const view = ledger.data.payload;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>season ledger · {view.season}</div>
          <h1 className={styles.title}>History</h1>
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
      {view.rows.length === 0 ? (
        <EmptyState title="No decision recorded yet.">
          The first row appears once gameweek 1 is decided.
        </EmptyState>
      ) : (
        <Card title="Decisions" aside="each row is a frozen, checksummed ledger entry">
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
          captured {utcShort(row.deadline_utc)} deadline · {row.solver_status}
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
