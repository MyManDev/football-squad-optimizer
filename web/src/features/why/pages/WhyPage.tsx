import { Fragment } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { usePool, useRecommendation } from "../../../data/queries";
import type { PoolPlayerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { points, pounds, shortDigest, utcShort } from "../../../lib/format";
import styles from "./WhyPage.module.css";

const POSITIONS: Array<PoolPlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function WhyPage() {
  const params = useParams();
  const season = params.season;
  const gameweek = params.gameweek ? Number(params.gameweek) : undefined;
  const recommendation = useRecommendation(season, gameweek);
  const pool = usePool(season, gameweek);

  if (!season || !gameweek) return <EmptyState title="Which gameweek?" />;
  if (recommendation.isPending || pool.isPending) return <EmptyState title="Loading…" />;
  if (recommendation.isError || pool.isError) {
    const error = recommendation.error ?? pool.error;
    return (
      <EmptyState
        title={
          error instanceof NotFoundError
            ? "No decision for this gameweek."
            : "This decision could not be shown."
        }
      >
        {String(error?.message)}
      </EmptyState>
    );
  }
  const view = recommendation.data.payload;
  const poolView = pool.data.payload;
  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>
          <Link to={`/gw/${season}/${gameweek}`}>← Gameweek {gameweek}</Link> · {view.season}
        </div>
        <h1 className={styles.title}>Why these players</h1>
        <p className={styles.lede}>
          The solver picks the squad with the highest projected points under the game&apos;s rules;
          below is the top of the projected pool per position, with the frozen squad marked. A
          better-projected player who is not selected was priced out, capped by his club&apos;s
          three-player limit, or displaced by the formation.
        </p>
      </header>

      <div className={styles.grid}>
        {POSITIONS.map((position) => (
          <Card key={position} title={position} aside={`top ${poolView.per_position} of the pool`}>
            <table className={styles.table}>
              <caption className="visually-hidden">Projected pool, {position}</caption>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">player</th>
                  <th scope="col" className={styles.right}>
                    price
                  </th>
                  <th scope="col" className={styles.right}>
                    xP
                  </th>
                  <th scope="col">in squad</th>
                </tr>
              </thead>
              <tbody>
                {poolView.players
                  .filter((p) => p.position === position)
                  .map((p) => (
                    <tr key={p.player_id} className={p.selected ? styles.selected : undefined}>
                      <td className="num">{p.rank_in_position}</td>
                      <td>
                        <div>{p.name}</div>
                        <div className={styles.sub}>{p.team}</div>
                      </td>
                      <td className={`${styles.right} num`}>{pounds(p.price_tenths)}</td>
                      <td className={`${styles.right} num`}>{points(p.expected_points)}</td>
                      <td>
                        {p.role === "starter" ? (
                          <Badge tone="accent">XI</Badge>
                        ) : p.role === "bench" ? (
                          <Badge>bench</Badge>
                        ) : (
                          <span className={styles.sub}>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>

      <RiskAndProvenance view={view} />
    </div>
  );
}

function RiskAndProvenance({ view }: { view: RecommendationView }) {
  const meta = view.metadata as Record<string, unknown>;
  return (
    <div className={styles.grid}>
      <Card title="Risk view" aside={<Badge>{view.risk.status.replace("_", " ")}</Badge>}>
        <p className={styles.para}>{view.risk.reason}</p>
        {view.risk.blockers.length > 0 && (
          <p className={styles.sub}>blockers: {view.risk.blockers.join(", ")}</p>
        )}
        <ul className={styles.list}>
          {view.risk.stated_limits.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Card>
      <Card title="Provenance">
        <dl className={styles.dl}>
          <dt>capture</dt>
          <dd>
            {view.snapshot_id} · {utcShort(view.captured_at_utc)}
          </dd>
          <dt>model</dt>
          <dd>
            {view.model_name}@{view.model_version}
          </dd>
          <dt>features</dt>
          <dd>{view.feature_contract_version}</dd>
          <dt>projection digest</dt>
          <dd className="mono">{shortDigest(view.prediction_fingerprint, 16)}</dd>
          <dt>solver</dt>
          <dd>
            {view.solver_status}
            {view.solver_proved_optimal ? " (proved)" : ""}
          </dd>
          <dt>unavailable in pool</dt>
          <dd>{view.unavailable_player_count}</dd>
          {Object.entries(meta)
            .filter(([, value]) => typeof value !== "object")
            .map(([key, value]) => (
              <Fragment key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd className={typeof value === "string" && value.length > 24 ? "mono" : ""}>
                  {String(value)}
                </dd>
              </Fragment>
            ))}
        </dl>
      </Card>
    </div>
  );
}
