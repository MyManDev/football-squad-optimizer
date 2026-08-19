import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, useRecommendation } from "../../../data/queries";
import type { RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import {
  countdown,
  local,
  percent,
  points,
  pounds,
  shortDigest,
  utcShort,
} from "../../../lib/format";
import { Pitch } from "../components/Pitch";
import styles from "./ThisWeekPage.module.css";

/** A clock that ticks every `intervalMs`; the countdown text is derived during render. */
function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function ThisWeekPage() {
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);

  if (index.isPending || (season && gameweek && recommendation.isPending)) {
    return <EmptyState title="Loading the latest decision…" />;
  }
  if (index.isError) {
    return <EmptyState title="The site data could not be read.">{String(index.error)}</EmptyState>;
  }
  if (!season || !gameweek) {
    return (
      <EmptyState title="No decision recorded yet.">
        The first gameweek is decided about two hours before its deadline; the page fills in once
        the ledger holds an entry.
      </EmptyState>
    );
  }
  if (recommendation.isError) {
    const error = recommendation.error;
    return (
      <EmptyState
        title={
          error instanceof NotFoundError
            ? "No decision for this gameweek."
            : "This decision could not be shown."
        }
      >
        {String(error.message)}
      </EmptyState>
    );
  }
  if (!recommendation.data) return null;
  return (
    <Decision view={recommendation.data.payload} generatedAt={recommendation.data.generatedAtUtc} />
  );
}

function Decision({ view, generatedAt }: { view: RecommendationView; generatedAt: string }) {
  const now = useNow(30_000);
  const remaining = countdown(view.deadline_utc, now);
  const risk = view.risk;
  const captain = view.starting_xi.find((p) => p.is_captain);
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {view.season} ·{" "}
            {view.decision_kind === "opening" ? "opening squad" : "transfer decision"}
          </div>
          <h1 className={styles.title}>Gameweek {view.gameweek}</h1>
          <Link className={styles.whyLink} to={`/why/${view.season}/${view.gameweek}`}>
            Why these players →
          </Link>
        </div>
        <div className={styles.deadline}>
          <div className={styles.kicker}>deadline {remaining === "closed" ? "" : "in"}</div>
          <div className={`${styles.countdown} num`}>{remaining || "—"}</div>
          <div className={styles.kicker} title={view.deadline_utc}>
            {local(view.deadline_utc)}
          </div>
        </div>
      </header>

      <StatRow>
        <Stat
          label="projected score"
          value={points(view.projected_score)}
          note={
            risk.status === "available" && risk.lower_quantile_score !== null
              ? `lower ${percent(risk.lower_quantile_probability ?? 0)} tail ${points(risk.lower_quantile_score)}`
              : "lower tail: not evaluated"
          }
        />
        <Stat
          label={view.decision_kind === "opening" ? "squad cost" : "squad sell value"}
          value={pounds(view.total_cost_tenths)}
          note={
            view.transfers
              ? `bank ${pounds(view.transfers.bank_after_tenths)} · ${view.transfers.free_transfers_after} FT left`
              : "budget £100.0m"
          }
        />
        <Stat
          label="solver"
          value={view.solver_status}
          tone={view.solver_proved_optimal ? "accent" : "muted"}
          note={
            view.solver_proved_optimal
              ? "proved optimal, single thread"
              : "not proved — reported, not recommended"
          }
        />
      </StatRow>

      <Card
        tone="pitch"
        title="Starting XI"
        aside={`${view.starting_xi.length} starters · captain counted twice`}
      >
        <Pitch starters={view.starting_xi} />
      </Card>

      <div className={styles.twoUp}>
        <Card title="Captain">
          {captain ? (
            <div className={styles.captainLine}>
              <strong>{captain.name}</strong>
              <span className={styles.muted}>
                {captain.team} · {captain.position} · {points(captain.expected_points)} xP, counted
                twice
              </span>
            </div>
          ) : (
            <span className={styles.muted}>Captain not in the starting eleven.</span>
          )}
        </Card>
        <Card title="Transfers">
          {view.transfers ? (
            <TransfersBlock view={view} />
          ) : (
            <span className={styles.muted}>Opening squad — no transfers, no chip.</span>
          )}
        </Card>
      </div>

      <Card
        tone="muted"
        title="What these numbers do not say"
        aside={
          <Badge tone={risk.status === "available" ? "good" : "neutral"}>
            risk {risk.status.replace("_", " ")}
          </Badge>
        }
      >
        <p className={styles.limit}>{risk.reason}</p>
        {risk.status === "available" && (
          <StatRow>
            <Stat
              label={`P(score < ${risk.points_threshold ?? "?"})`}
              value={
                risk.probability_below_threshold !== null
                  ? percent(risk.probability_below_threshold)
                  : "—"
              }
              note={
                risk.probability_below_threshold_interval
                  ? `90% [${percent(risk.probability_below_threshold_interval[0])}, ${percent(risk.probability_below_threshold_interval[1])}]`
                  : undefined
              }
            />
            <Stat
              label="mean of scenarios"
              value={risk.mean_score !== null ? points(risk.mean_score) : "—"}
              note={
                risk.location_shift_points !== null
                  ? `shifted ${points(risk.location_shift_points)} for selection optimism`
                  : undefined
              }
            />
            <Stat
              label={`mean worst ${percent(risk.worst_fraction ?? 0)}`}
              value={
                risk.mean_worst_fraction_score !== null
                  ? points(risk.mean_worst_fraction_score)
                  : "—"
              }
              note={risk.scenario_count !== null ? `${risk.scenario_count} scenarios` : undefined}
            />
          </StatRow>
        )}
        {risk.rivals.length > 0 && (
          <ul className={styles.list}>
            {risk.rivals.map((r) => (
              <li key={r.rival}>
                vs {r.rival}: P(ahead) {percent(r.probability_ahead)} [
                {percent(r.probability_ahead_interval[0])},{" "}
                {percent(r.probability_ahead_interval[1])}], {r.shared_starters} shared starters
              </li>
            ))}
          </ul>
        )}
        {risk.stated_limits.length > 0 && (
          <ul className={styles.list}>
            {risk.stated_limits.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Bench" aside="in substitution order">
        <div className={styles.bench}>
          {view.bench.map((p) => (
            <div key={p.player_id} className={styles.benchRow}>
              <span className={`${styles.benchOrder} num`}>{p.bench_order}</span>
              <span className={styles.benchName}>
                <strong>{p.name}</strong>
                <span className={styles.muted}>
                  {p.team} · {p.position} · {pounds(p.price_tenths)}
                </span>
              </span>
              <span className={`${styles.benchXp} num`}>{points(p.expected_points)}</span>
            </div>
          ))}
        </div>
      </Card>

      <footer className={styles.provenance}>
        <span>
          captured {utcShort(view.captured_at_utc)} · {view.snapshot_id}
        </span>
        <span>
          {view.model_name}@{view.model_version} · {view.feature_contract_version} · projection{" "}
          {shortDigest(view.prediction_fingerprint)}
        </span>
        <span>
          {view.report_contract_version} · page generated {utcShort(generatedAt)}
          {view.settled && view.outcome_realized_score !== null
            ? ` · settled: ${points(view.outcome_realized_score)} realized`
            : ""}
        </span>
      </footer>
    </div>
  );
}

function TransfersBlock({ view }: { view: RecommendationView }) {
  const t = view.transfers;
  if (!t) return null;
  return (
    <div className={styles.transfers}>
      <div className={styles.muted}>
        {t.transfer_count} transfer{t.transfer_count === 1 ? "" : "s"} · {t.paid_transfer_count}{" "}
        paid ({points(t.transfer_hit_points, 0)} pts) · FT {t.free_transfers_before}→
        {t.free_transfers_after} · bank {pounds(t.bank_before_tenths)}→{pounds(t.bank_after_tenths)}
        {t.chip ? ` · chip: ${t.chip}` : ""}
      </div>
      <div className={styles.transferCols}>
        <div>
          <div className={styles.kicker}>out</div>
          {t.transfers_out.map((p) => (
            <div key={p.player_id}>
              {p.name} <span className={styles.muted}>{pounds(p.price_tenths)}</span>
            </div>
          ))}
        </div>
        <div>
          <div className={styles.kicker}>in</div>
          {t.transfers_in.map((p) => (
            <div key={p.player_id}>
              {p.name} <span className={styles.muted}>{pounds(p.price_tenths)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
