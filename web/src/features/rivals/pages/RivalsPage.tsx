import { Fragment } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, usePool, useRecommendation } from "../../../data/queries";
import type { PoolPlayerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { percent, points, pounds } from "../../../lib/format";
import { PointsBar, ProbabilityBar } from "../components/ProbabilityBar";
import styles from "./RivalsPage.module.css";

const POSITIONS: Array<PoolPlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function RivalsPage() {
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);
  const pool = usePool(season, gameweek);

  if (index.isPending || (season && gameweek && (recommendation.isPending || pool.isPending))) {
    return <EmptyState title="Loading the projections…" />;
  }
  if (index.isError || recommendation.isError || pool.isError) {
    const error = index.error ?? recommendation.error ?? pool.error;
    return (
      <EmptyState
        title={
          error instanceof NotFoundError
            ? "No decision for this gameweek."
            : "The analysis could not be shown."
        }
      >
        {String(error?.message)}
      </EmptyState>
    );
  }
  if (!season || !gameweek || !recommendation.data || !pool.data) {
    return (
      <EmptyState title="Nothing to compare yet.">
        Projections and rival comparisons appear once a gameweek has been decided.
      </EmptyState>
    );
  }
  const view = recommendation.data.payload;
  const poolView = pool.data.payload;
  const maxByPosition = new Map(
    POSITIONS.map((position) => [
      position,
      Math.max(
        1,
        ...poolView.players.filter((p) => p.position === position).map((p) => p.expected_points),
      ),
    ]),
  );
  return (
    <div className={styles.page}>
      <header>
        <div className={styles.kicker}>
          {view.season} · gameweek {view.gameweek} · pool of {poolView.pool_size} players
        </div>
        <h1 className={styles.title}>Rival analysis</h1>
        <p className={styles.lede}>
          Two questions on one page: who else could have been picked (the projections the solver
          chose from), and how the chosen squad compares with a rival&apos;s in the same scenarios.
        </p>
      </header>

      <Rivals view={view} />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Projections</h2>
        <p className={styles.sectionLede}>
          The top of the pool per position, ranked by projected points, with the frozen squad
          marked. A better-projected player who is not selected was priced out, capped by his
          club&apos;s three-player limit, or displaced by the formation.
        </p>
        <div className={styles.grid}>
          {POSITIONS.map((position) => (
            <Card
              key={position}
              title={position}
              aside={`top ${poolView.per_position} of the pool`}
            >
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
                        <td className={`${styles.right} num`}>
                          {points(p.expected_points)}
                          <PointsBar
                            value={p.expected_points}
                            max={maxByPosition.get(position) ?? 1}
                          />
                        </td>
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
      </section>

      <Card tone="muted" title="Provenance">
        <dl className={styles.dl}>
          <dt>capture</dt>
          <dd>{view.snapshot_id}</dd>
          <dt>model</dt>
          <dd>
            {view.model_name}@{view.model_version}
          </dd>
          <dt>features</dt>
          <dd>{view.feature_contract_version}</dd>
          <dt>unavailable in pool</dt>
          <dd>{view.unavailable_player_count}</dd>
          {Object.entries(view.metadata as Record<string, unknown>)
            .filter(([, value]) => typeof value !== "object")
            .map(([key, value]) => (
              <Fragment key={key}>
                <dt>{key.replace(/_/g, " ")}</dt>
                <dd>{String(value)}</dd>
              </Fragment>
            ))}
        </dl>
      </Card>
    </div>
  );
}

function Rivals({ view }: { view: RecommendationView }) {
  const rivals = view.risk.rivals;
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Against rivals</h2>
      {rivals.length === 0 ? (
        <EmptyState title="No rival was scored against this decision.">
          A rival comparison needs two things this gameweek does not have: a decision whose risk
          view was evaluated (this one is <strong>{view.risk.status.replace("_", " ")}</strong>),
          and a rival squad to score in the same scenarios. Both are being wired up — the template
          rival comes from the capture&apos;s ownership, mini-league rivals from the entry data.
          Until then this page shows the projections below rather than a probability nobody
          measured.
        </EmptyState>
      ) : (
        <Card title="Probability of finishing ahead" aside="same scenarios, shared players cancel">
          <table className={styles.rivalTable}>
            <caption className="visually-hidden">Rival comparisons</caption>
            <thead>
              <tr>
                <th scope="col">rival</th>
                <th scope="col">P(ahead) with 90% interval</th>
                <th scope="col" className={styles.right}>
                  P
                </th>
                <th scope="col" className={styles.right}>
                  mean gap
                </th>
                <th scope="col" className={styles.right}>
                  shared
                </th>
              </tr>
            </thead>
            <tbody>
              {rivals.map((rival) => (
                <tr key={rival.rival}>
                  <td>{rival.rival}</td>
                  <td>
                    <ProbabilityBar
                      probability={rival.probability_ahead}
                      interval={rival.probability_ahead_interval}
                      label={`probability of finishing ahead of ${rival.rival}`}
                    />
                  </td>
                  <td className={`${styles.right} num`}>{percent(rival.probability_ahead)}</td>
                  <td className={`${styles.right} num`}>{points(rival.mean_difference)}</td>
                  <td className={`${styles.right} num`}>{rival.shared_starters}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {view.risk.stated_limits.length > 0 && (
            <ul className={styles.list}>
              {view.risk.stated_limits.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </Card>
      )}
      <p className={styles.sub}>
        Where the squad itself came from is on <Link to="/">the squad page</Link>; how the season
        compares with everyone else is on <Link to="/league">the league page</Link>.
      </p>
    </section>
  );
}
