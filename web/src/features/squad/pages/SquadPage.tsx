import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { NotFoundError } from "../../../data/client";
import { useIndex, useLedger, useRecommendation } from "../../../data/queries";
import type { LedgerView, RecommendationView } from "../../../data/schema";
import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { Stat, StatRow } from "../../../design/components/Stat";
import { useLanguage } from "../../../i18n/context";
import { riskText } from "../../../i18n/reasons";
import {
  countdown,
  local,
  percent,
  points,
  pounds,
  shortDigest,
  signedPoints,
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
  // Deliberately not part of the pending or error guards below: the season card is extra
  // context, so a slow or missing ledger must not delay or break the decision itself.
  const ledger = useLedger(season);

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
    <Squad
      view={recommendation.data.payload}
      generatedAt={recommendation.data.generatedAtUtc}
      ledger={ledger.data?.payload ?? null}
    />
  );
}

/**
 * Where the season stands, from the ledger the site already publishes.
 *
 * The season total is `total_realized_net_score` rather than `total_realized_score`, because
 * net is the number the platform itself shows and the gross one overstates it by every
 * transfer hit taken. There is no per-row cumulative *net* field in `ui_view_v1`, so this card
 * reports the season total as a season total and does not claim an as-of-this-gameweek figure
 * on a historical view.
 */
function SeasonStanding({ ledger }: { ledger: LedgerView }) {
  const { locale, messages } = useLanguage();
  const copy = messages.squad;
  const settled = ledger.rows.filter((row) => row.settled && row.realized_net_score !== null);
  const latest = settled.length > 0 ? settled[settled.length - 1] : null;
  return (
    <Card title={copy.seasonTitle} aside={<Badge tone="neutral">{ledger.season}</Badge>}>
      <StatRow>
        <Stat
          label={copy.seasonNet}
          value={
            ledger.total_realized_net_score === null
              ? "—"
              : points(ledger.total_realized_net_score, 0, locale)
          }
          tone="accent"
          note={copy.seasonNetNote(
            ledger.settled_gameweeks,
            points(ledger.total_transfer_hit_points, 0, locale),
          )}
        />
        <Stat
          label={copy.seasonLatestWeek}
          value={latest === null ? "—" : points(latest.realized_net_score as number, 0, locale)}
          note={
            latest === null
              ? undefined
              : copy.seasonLatestWeekNote(
                  messages.common.gameweekShort(latest.gameweek),
                  points(latest.projected_score, 1, locale),
                )
          }
        />
        <Stat
          label={copy.seasonVsProjection}
          value={
            ledger.total_projection_error === null
              ? "—"
              : signedPoints(ledger.total_projection_error, 1, locale)
          }
          note={copy.seasonVsProjectionNote}
        />
      </StatRow>
    </Card>
  );
}

function Squad({
  view,
  generatedAt,
  ledger,
}: {
  view: RecommendationView;
  generatedAt: string;
  ledger: LedgerView | null;
}) {
  const { locale, messages } = useLanguage();
  const copy = messages.squad;
  const now = useNow(30_000);
  const remaining = countdown(view.deadline_utc, now, {
    closed: messages.common.closed,
    day: messages.common.dayShort,
  });
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
            {remaining.isClosed ? copy.deadline : copy.deadlineIn}
          </div>
          <div className={`${styles.countdown} num`}>{remaining.text || "—"}</div>
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

      {ledger && ledger.settled_gameweeks > 0 ? <SeasonStanding ledger={ledger} /> : null}

      {view.settled && view.outcome_realized_score !== null ? (
        <Card title={copy.settledTitle} aside={<Badge tone="good">{copy.settledAside}</Badge>}>
          <StatRow>
            <Stat label={copy.settledProjected} value={points(view.projected_score, 1, locale)} />
            <Stat
              label={copy.settledRealizedLabel}
              value={points(view.outcome_realized_score, 0, locale)}
            />
            <Stat
              label={copy.settledNet}
              value={
                view.outcome_net_score === null ? "—" : points(view.outcome_net_score, 0, locale)
              }
              note={copy.settledNetNote}
            />
          </StatRow>
          <p className={styles.settledNote}>{copy.settledNote}</p>
        </Card>
      ) : null}

      <Card tone="pitch" title={copy.startingXi} aside={copy.starterCount(view.starting_xi.length)}>
        <Pitch
          starters={view.starting_xi}
          showOutcomes={view.settled}
          captainMultiplier={view.captain_multiplier}
        />
      </Card>

      <div className={styles.twoUp}>
        <Card title={copy.captain}>
          {captain ? (
            <div className={styles.captainLine}>
              <strong>{captain.name}</strong>
              <span className={styles.muted}>
                {captain.team} · {captain.position} · {points(captain.expected_points, 1, locale)}{" "}
                xP, {copy.captainMultiplier(view.captain_multiplier)}
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
        <p className={styles.limit}>
          {riskText(messages, risk.status, risk.blockers, risk.reason)}
        </p>
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

      {/* The full identity chain stays on the page — it is what makes the decision
          auditable — but folded away: a reader wants the squad, an auditor can open it. */}
      <footer className={styles.provenance}>
        <details>
          <summary>
            {copy.recordIdentity} · {utcShort(view.captured_at_utc, locale)}
          </summary>
          <div className={styles.provenanceDetail}>
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
          </div>
        </details>
      </footer>
    </div>
  );
}
