import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, useRecommendation } from "../../../data/queries";
import type { RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
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
import styles from "./SquadPage.module.css";

/** A clock that ticks; the countdown text is derived during render. */
function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function SquadPage() {
  const { messages } = useLanguage();
  const copy = messages.squad;
  const params = useParams();
  const index = useIndex();
  const latest = index.data?.payload.latest ?? null;
  const season = params.season ?? latest?.season ?? undefined;
  const gameweek = params.gameweek ? Number(params.gameweek) : (latest?.gameweek ?? undefined);
  const recommendation = useRecommendation(season, gameweek);

  if (index.isPending || (season && gameweek && recommendation.isPending)) {
    return <EmptyState title={copy.loading} />;
  }
  if (index.isError) {
    return <EmptyState title={copy.dataError}>{String(index.error)}</EmptyState>;
  }
  if (!season || !gameweek) {
    return (
      <EmptyState title={messages.common.noDecisionRecorded}>{copy.noDecisionBody}</EmptyState>
    );
  }
  if (recommendation.isError) {
    const error = recommendation.error;
    return (
      <EmptyState
        title={
          error instanceof NotFoundError
            ? messages.common.noDecisionForGameweek
            : copy.decisionError
        }
      >
        {String(error.message)}
      </EmptyState>
    );
  }
  if (!recommendation.data) return null;
  return (
    <Squad view={recommendation.data.payload} generatedAt={recommendation.data.generatedAtUtc} />
  );
}

function Squad({ view, generatedAt }: { view: RecommendationView; generatedAt: string }) {
  const { language, locale, messages } = useLanguage();
  const copy = messages.squad;
  const now = useNow(30_000);
  const remaining = countdown(view.deadline_utc, now, language);
  const risk = view.risk;
  const captain = view.starting_xi.find((p) => p.is_captain);
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <div className={styles.kicker}>
            {view.season} ·{" "}
            {view.decision_kind === "opening" ? copy.openingSquad : copy.transferDecision}
          </div>
          <h1 className={styles.title}>{messages.common.gameweek(view.gameweek)}</h1>
          <Link className={styles.whyLink} to="/rivals">
            {copy.why}
          </Link>
        </div>
        <div className={styles.deadline}>
          <div className={styles.kicker}>
            {remaining === messages.common.closed ? copy.deadline : copy.deadlineIn}
          </div>
          <div className={`${styles.countdown} num`}>{remaining || "—"}</div>
          <div className={styles.kicker} title={view.deadline_utc}>
            {local(view.deadline_utc, locale)}
          </div>
        </div>
      </header>

      <StatRow>
        <Stat
          label={copy.projectedScore}
          value={points(view.projected_score, 1, locale)}
          note={
            risk.status === "available" && risk.lower_quantile_score !== null
              ? copy.lowerTail(
                  percent(risk.lower_quantile_probability ?? 0, 0, locale),
                  points(risk.lower_quantile_score, 1, locale),
                )
              : copy.lowerTailUnavailable
          }
        />
        <Stat
          label={view.decision_kind === "opening" ? copy.squadCost : copy.squadSellValue}
          value={pounds(view.total_cost_tenths)}
          note={
            view.transfers
              ? copy.bankAndFt(
                  pounds(view.transfers.bank_after_tenths),
                  view.transfers.free_transfers_after,
                )
              : copy.budget
          }
        />
        <Stat
          label={copy.solver}
          value={view.solver_status}
          tone={view.solver_proved_optimal ? "accent" : "muted"}
          note={view.solver_proved_optimal ? copy.provedOptimal : copy.notProved}
        />
      </StatRow>

      <Card tone="pitch" title={copy.startingXi} aside={copy.starterCount(view.starting_xi.length)}>
        <Pitch starters={view.starting_xi} />
      </Card>

      <div className={styles.twoUp}>
        <Card title={copy.captain}>
          {captain ? (
            <div className={styles.captainLine}>
              <strong>{captain.name}</strong>
              <span className={styles.muted}>
                {captain.team} · {captain.position} · {points(captain.expected_points, 1, locale)}{" "}
                xP, {copy.countedTwice}
              </span>
            </div>
          ) : (
            <span className={styles.muted}>{copy.noCaptain}</span>
          )}
        </Card>
        <Card title={copy.bench} aside={copy.substitutionOrder}>
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
                <span className={`${styles.benchXp} num`}>
                  {points(p.expected_points, 1, locale)}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card
        tone="muted"
        title={copy.limitsTitle}
        aside={
          <Badge tone={risk.status === "available" ? "good" : "neutral"}>
            {copy.risk} {copy.riskStatus[risk.status]}
          </Badge>
        }
      >
        <p className={styles.limit}>{risk.reason}</p>
        {risk.status === "available" && (
          <StatRow>
            <Stat
              label={`P(${copy.score} < ${risk.points_threshold ?? "?"})`}
              value={
                risk.probability_below_threshold !== null
                  ? percent(risk.probability_below_threshold, 0, locale)
                  : "—"
              }
              note={
                risk.probability_below_threshold_interval
                  ? `90% [${percent(risk.probability_below_threshold_interval[0], 0, locale)}, ${percent(risk.probability_below_threshold_interval[1], 0, locale)}]`
                  : undefined
              }
            />
            <Stat
              label={copy.scenarioMean}
              value={risk.mean_score !== null ? points(risk.mean_score, 1, locale) : "—"}
              note={
                risk.location_shift_points !== null
                  ? copy.shiftedForOptimism(points(risk.location_shift_points, 1, locale))
                  : undefined
              }
            />
            <Stat
              label={copy.meanWorst(percent(risk.worst_fraction ?? 0, 0, locale))}
              value={
                risk.mean_worst_fraction_score !== null
                  ? points(risk.mean_worst_fraction_score, 1, locale)
                  : "—"
              }
              note={
                risk.scenario_count !== null ? copy.scenarioCount(risk.scenario_count) : undefined
              }
            />
          </StatRow>
        )}
        {risk.stated_limits.length > 0 && (
          <ul className={styles.list}>
            {risk.stated_limits.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {risk.rivals.length > 0 && (
          <p className={styles.muted}>
            <Link to="/rivals">{copy.rivalComparisons}</Link>
          </p>
        )}
      </Card>

      <footer className={styles.provenance}>
        <span>
          {copy.captured} {utcShort(view.captured_at_utc, locale)} · {view.snapshot_id}
        </span>
        <span>
          {view.model_name}@{view.model_version} · {view.feature_contract_version} ·{" "}
          {copy.projection} {shortDigest(view.prediction_fingerprint)}
        </span>
        <span>
          {view.report_contract_version} · {copy.generated} {utcShort(generatedAt, locale)}
          {view.settled && view.outcome_realized_score !== null
            ? ` · ${copy.settledRealized(points(view.outcome_realized_score, 1, locale))}`
            : ""}
        </span>
      </footer>
    </div>
  );
}
