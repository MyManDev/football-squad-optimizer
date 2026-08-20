import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, useRecommendation } from "../../../data/queries";
import type { PlayerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { local, points, pounds } from "../../../lib/format";
import { DecisionControls } from "../components/DecisionControls";
import styles from "./MovesPage.module.css";

export function MovesPage() {
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);

  if (index.isPending || (season && gameweek && recommendation.isPending)) {
    return <EmptyState title="Loading the proposed moves…" />;
  }
  if (index.isError || recommendation.isError) {
    const error = index.error ?? recommendation.error;
    return (
      <EmptyState
        title={
          error instanceof NotFoundError
            ? "No decision for this gameweek."
            : "The moves could not be shown."
        }
      >
        {String(error?.message)}
      </EmptyState>
    );
  }
  if (!season || !gameweek || !recommendation.data) {
    return (
      <EmptyState title="No decision recorded yet.">
        Moves appear once a gameweek has been decided.
      </EmptyState>
    );
  }
  return <Moves view={recommendation.data.payload} />;
}

function Moves({ view }: { view: RecommendationView }) {
  const t = view.transfers;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {view.season} · gameweek {view.gameweek} · deadline {local(view.deadline_utc)}
          </div>
          <h1 className={styles.title}>Suggested moves</h1>
        </div>
        {t?.chip ? <Badge tone="accent">chip: {t.chip}</Badge> : null}
      </header>

      <DecisionControls />

      {!t ? (
        <EmptyState title="Opening squad — no transfers to make.">
          Gameweek 1 builds the squad from scratch, so there is nothing to move. The first wildcard
          and the other chips open in gameweek 2; from then on this page carries the planner&apos;s
          proposed transfers, what they cost in points, and the state they leave the bank and the
          free transfers in. See the <Link to="/">squad it built</Link>.
        </EmptyState>
      ) : (
        <>
          <StatRow>
            <Stat
              label="transfers"
              value={`${t.transfer_count}`}
              note={`${t.paid_transfer_count} paid · ${points(t.transfer_hit_points, 0)} points charged`}
            />
            <Stat
              label="free transfers"
              value={`${t.free_transfers_before} → ${t.free_transfers_after}`}
              note={`cap ${t.max_free_transfers}; the planner priced a hit at ${points(t.transfer_hit_cost_points, 0)}`}
            />
            <Stat
              label="bank"
              value={pounds(t.bank_after_tenths)}
              note={`from ${pounds(t.bank_before_tenths)} · squad value ${pounds(t.squad_sell_value_tenths)}`}
            />
          </StatRow>

          <div className={styles.twoUp}>
            <Card title="Out" aside={`${t.transfers_out.length} leaving`}>
              <MoveList players={t.transfers_out} />
            </Card>
            <Card title="In" aside={`${t.transfers_in.length} arriving`}>
              <MoveList players={t.transfers_in} />
            </Card>
          </div>

          <Card tone="muted" title="What this proposal rests on">
            <ul className={styles.list}>
              <li>
                The planner maximises the projection it was given over its horizon; a transfer is
                worth making only if that projection is right about the players involved.
              </li>
              <li>
                Prices are the capture&apos;s: outgoing players are valued at their sell price
                (purchase plus half of any rise), incoming at the price shown.
              </li>
              <li>
                Chips are offered inside their published windows only; a chip that is not shown was
                either unavailable or worth less than holding it.
              </li>
              <li>Planner contract {t.planner_solver_status.toLowerCase()} at decision time.</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function MoveList({ players }: { players: PlayerView[] }) {
  if (players.length === 0) return <span className={styles.muted}>None.</span>;
  return (
    <div className={styles.moves}>
      {players.map((p) => (
        <div key={p.player_id} className={styles.move}>
          <span className={styles.moveName}>
            <strong>{p.name}</strong>
            <span className={styles.muted}>
              {p.team} · {p.position}
            </span>
          </span>
          <span className={`${styles.movePrice} num`}>{pounds(p.price_tenths)}</span>
          <span className={`${styles.moveXp} num`}>{points(p.expected_points)} xP</span>
        </div>
      ))}
    </div>
  );
}
