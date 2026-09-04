import { Fragment } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, usePool, useRecommendation } from "../../../data/queries";
import type { PoolPlayerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { percent, points, pounds } from "../../../lib/format";
import { PointsBar, ProbabilityBar } from "../components/ProbabilityBar";
import styles from "./RivalsPage.module.css";

const POSITIONS: Array<PoolPlayerView["position"]> = ["GK", "DEF", "MID", "FWD"];

export function RivalsPage() {
  const { locale, messages } = useLanguage();
  const copy = messages.rivals;
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);
  const pool = usePool(season, gameweek);

  if (index.isPending || (season && gameweek && (recommendation.isPending || pool.isPending))) {
    return <EmptyState title={copy.loading} />;
  }
  if (index.isError || recommendation.isError || pool.isError) {
    const error = index.error ?? recommendation.error ?? pool.error;
    return (
      <EmptyState
        title={error instanceof NotFoundError ? messages.common.noDecisionForGameweek : copy.error}
      >
        {String(error?.message)}
      </EmptyState>
    );
  }
  if (!season || !gameweek || !recommendation.data || !pool.data) {
    return <EmptyState title={copy.nothingTitle}>{copy.nothingBody}</EmptyState>;
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
          {copy.kicker(view.season, view.gameweek, poolView.pool_size)}
        </div>
        <h1 className={styles.title}>{copy.title}</h1>
        <p className={styles.lede}>{copy.lede}</p>
      </header>

      <Rivals view={view} />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{copy.projections}</h2>
        <p className={styles.sectionLede}>{copy.projectionsBody}</p>
        <div className={styles.grid}>
          {POSITIONS.map((position) => (
            <Card key={position} title={position} aside={copy.topPool(poolView.per_position)}>
              <table className={styles.table}>
                <caption className="visually-hidden">{copy.projectedPool(position)}</caption>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">{copy.player}</th>
                    <th scope="col" className={styles.right}>
                      {copy.price}
                    </th>
                    <th scope="col" className={styles.right}>
                      xP
                    </th>
                    <th scope="col">{copy.inSquad}</th>
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
                          {points(p.expected_points, 1, locale)}
                          <PointsBar
                            value={p.expected_points}
                            max={maxByPosition.get(position) ?? 1}
                          />
                        </td>
                        <td>
                          {p.role === "starter" ? (
                            <Badge tone="accent">XI</Badge>
                          ) : p.role === "bench" ? (
                            <Badge>{copy.bench}</Badge>
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

      <Card tone="muted" title={copy.provenance}>
        <dl className={styles.dl}>
          <dt>{copy.capture}</dt>
          <dd>{view.snapshot_id}</dd>
          <dt>{copy.model}</dt>
          <dd>
            {view.model_name}@{view.model_version}
          </dd>
          <dt>{copy.features}</dt>
          <dd>{view.feature_contract_version}</dd>
          <dt>{copy.unavailable}</dt>
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
  const { locale, messages } = useLanguage();
  const copy = messages.rivals;
  const rivals = view.risk.rivals;
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{copy.against}</h2>
      {rivals.length === 0 ? (
        <EmptyState title={copy.noRivalTitle}>
          {copy.noRivalBeforeStatus}
          <strong>{messages.squad.riskStatus[view.risk.status]}</strong>
          {copy.noRivalAfterStatus}
        </EmptyState>
      ) : (
        <Card title={copy.probabilityTitle} aside={copy.probabilityAside}>
          <table className={styles.rivalTable}>
            <caption className="visually-hidden">{copy.rivalComparisons}</caption>
            <thead>
              <tr>
                <th scope="col">{copy.rival}</th>
                <th scope="col">{copy.probabilityInterval}</th>
                <th scope="col" className={styles.right}>
                  P
                </th>
                <th scope="col" className={styles.right}>
                  {copy.meanGap}
                </th>
                <th scope="col" className={styles.right}>
                  {copy.shared}
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
                      label={copy.probabilityLabel(rival.rival)}
                    />
                  </td>
                  <td className={`${styles.right} num`}>
                    {percent(rival.probability_ahead, 0, locale)}
                  </td>
                  <td className={`${styles.right} num`}>
                    {points(rival.mean_difference, 1, locale)}
                  </td>
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
        {copy.linksBefore}
        <Link to="/">{copy.squadPage}</Link>
        {copy.linksMiddle}
        <Link to="/league">{copy.leaguePage}</Link>.
      </p>
    </section>
  );
}
