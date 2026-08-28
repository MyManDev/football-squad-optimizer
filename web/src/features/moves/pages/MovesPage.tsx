import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, useRecommendation } from "../../../data/queries";
import type { PlayerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { local, points, pounds } from "../../../lib/format";
import { DecisionControls } from "../components/DecisionControls";
import styles from "./MovesPage.module.css";

export function MovesPage() {
  const { messages } = useLanguage();
  const copy = messages.moves;
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);

  if (index.isPending || (season && gameweek && recommendation.isPending)) {
    return <EmptyState title={copy.loading} />;
  }
  if (index.isError || recommendation.isError) {
    const error = index.error ?? recommendation.error;
    return (
      <EmptyState
        title={error instanceof NotFoundError ? messages.common.noDecisionForGameweek : copy.error}
      >
        {String(error?.message)}
      </EmptyState>
    );
  }
  if (!season || !gameweek || !recommendation.data) {
    return (
      <EmptyState title={messages.common.noDecisionRecorded}>{copy.noDecisionBody}</EmptyState>
    );
  }
  return <Moves view={recommendation.data.payload} />;
}

function Moves({ view }: { view: RecommendationView }) {
  const { locale, messages } = useLanguage();
  const copy = messages.moves;
  const t = view.transfers;
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {view.season} · {messages.common.gameweek(view.gameweek)} · {copy.deadline}{" "}
            {local(view.deadline_utc, locale)}
          </div>
          <h1 className={styles.title}>{copy.title}</h1>
        </div>
        {t?.chip ? (
          <Badge tone="accent">
            {copy.chip}: {t.chip}
          </Badge>
        ) : null}
      </header>

      <DecisionControls horizonEvidence={view.metadata.horizon_evidence} />

      {!t ? (
        <EmptyState title={copy.openingTitle}>
          {copy.openingBeforeLink}
          <Link to="/">{copy.openingLink}</Link>.
        </EmptyState>
      ) : (
        <>
          <StatRow>
            <Stat
              label={copy.transfers}
              value={`${t.transfer_count}`}
              note={copy.transferNote(
                t.paid_transfer_count,
                points(t.transfer_hit_points, 0, locale),
              )}
            />
            <Stat
              label={copy.freeTransfers}
              value={`${t.free_transfers_before} → ${t.free_transfers_after}`}
              note={copy.freeTransferNote(
                t.max_free_transfers,
                points(t.transfer_hit_cost_points, 0, locale),
              )}
            />
            <Stat
              label={copy.bank}
              value={pounds(t.bank_after_tenths)}
              note={copy.bankNote(pounds(t.bank_before_tenths), pounds(t.squad_sell_value_tenths))}
            />
          </StatRow>

          <div className={styles.twoUp}>
            <Card title={copy.out} aside={copy.leaving(t.transfers_out.length)}>
              <MoveList players={t.transfers_out} />
            </Card>
            <Card title={copy.in} aside={copy.arriving(t.transfers_in.length)}>
              <MoveList players={t.transfers_in} />
            </Card>
          </div>

          <Card tone="muted" title={copy.restsOn}>
            <ul className={styles.list}>
              {copy.restsOnItems.map((item) => (
                <li key={item}>{item}</li>
              ))}
              <li>{copy.plannerContract(t.planner_solver_status.toLowerCase())}</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

function MoveList({ players }: { players: PlayerView[] }) {
  const { locale, messages } = useLanguage();
  if (players.length === 0) return <span className={styles.muted}>{messages.common.none}</span>;
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
          <span className={`${styles.moveXp} num`}>{points(p.expected_points, 1, locale)} xP</span>
        </div>
      ))}
    </div>
  );
}
