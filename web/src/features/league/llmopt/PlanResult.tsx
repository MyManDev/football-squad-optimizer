import { useId, type ReactNode } from "react";

import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures } from "../../../lib/clubs";
import { money, points, signedPoints } from "../../../lib/format";
import { useFixtures } from "../../fixtures/data";
import { COMPUTE_COPY, failureSentence, jobStanding } from "../advice/computeCopy";
import type { ComputePhase } from "../advice/useAdviceJob";
import { MemberBench, MemberPitch } from "../components/MemberPitch";
import { squadOnPitch } from "../pages/squadOnPitch";
import type { AdvicePlanWeek, EntryAdvice, EntrySquad } from "../types";
import { LLMOPT_COPY } from "./copy";
import { expectedNet, plannedWeeks, weekNet } from "./planComparison";
import styles from "./LLMOptPage.module.css";

function PlanSquad({ plan, squad }: { plan: EntryAdvice; squad: EntrySquad }) {
  const { language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const titleId = useId();
  const fixtures = useFixtures();
  const { starting_xi: eleven, bench, captain, vice_captain: vice } = plan;
  const starters = new Set(eleven?.map(({ player_id }) => player_id));
  if (
    eleven?.length !== 11 ||
    bench?.length !== 4 ||
    new Set([...starters, ...bench.map(({ player_id }) => player_id)]).size !== 15 ||
    !captain ||
    !vice ||
    captain.player_id === vice.player_id ||
    !starters.has(captain.player_id) ||
    !starters.has(vice.player_id)
  )
    return <p className={styles.muted}>{copy.lineupUnavailable}</p>;

  const onPitch = squadOnPitch(plan, squad);
  const codes = clubCodesFromFixtures(fixtures.data);
  return (
    <section className={styles.planSquad} aria-labelledby={titleId}>
      <h4 className={styles.lineupTitle} id={titleId}>
        {copy.lineup}
      </h4>
      <MemberPitch players={onPitch.eleven} codes={codes} />
      <MemberBench players={onPitch.bench} codes={codes} />
    </section>
  );
}

function UpcomingWeeks({ weeks }: { weeks: AdvicePlanWeek[] }) {
  const { language, locale, messages } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const titleId = useId();
  return (
    <section className={styles.laterWeeks} aria-labelledby={titleId}>
      <h4 id={titleId} className={styles.lineupTitle}>
        {copy.laterWeeks}
      </h4>
      {weeks.map((week) => {
        const chip = week.chip ? messages.leagueMembers.chipNames[week.chip] : null;
        return (
          <div key={week.gameweek} className={styles.laterWeek}>
            <h5>
              {copy.week} {week.gameweek}
            </h5>
            <dl className={styles.figures}>
              {chip && (
                <div>
                  <dt>{messages.leagueMembers.chipLabel}</dt>
                  <dd>{chip}</dd>
                </div>
              )}
              <div>
                <dt>{copy.clubTransfers}</dt>
                <dd>{week.transfers_in.map(({ name }) => name).join(", ") || copy.noPlayers}</dd>
              </div>
              <div>
                <dt>{copy.outgoing}</dt>
                <dd>{week.transfers_out.map(({ name }) => name).join(", ") || copy.noPlayers}</dd>
              </div>
              <div>
                <dt>{copy.net}</dt>
                <dd>{points(weekNet(week), 1, locale)}</dd>
              </div>
              <div>
                <dt>{copy.hits}</dt>
                <dd>{points(week.transfer_hit_points, 0, locale)}</dd>
              </div>
              <div>
                <dt>{copy.transfers}</dt>
                <dd>{week.free_transfers_after}</dd>
              </div>
            </dl>
          </div>
        );
      })}
    </section>
  );
}

function MetricDelta({ label, value }: { label: string; value?: string }) {
  if (value === undefined) return null;
  return (
    <small className={styles.metricDelta}>
      <span className="visually-hidden"> {label} </span>({value})
    </small>
  );
}

export type PreferencePrice = { key: string; label: string; ceiling?: number; detail?: string } & (
  | { status: "pending" | "conflict" | "unavailable" | "skipped" }
  | { status: "priced"; cost: number; aboveCeiling: boolean }
);

function PreferencePrices({ prices }: { prices: PreferencePrice[] }) {
  const titleId = useId();
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  if (!prices.length) return null;
  const price = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 3,
  });
  const statuses = {
    pending: copy.pricePending,
    conflict: copy.priceConflict,
    unavailable: copy.priceUnavailable,
    skipped: copy.priceNotRun,
  };
  return (
    <section className={styles.preferencePrices} aria-labelledby={titleId}>
      <h4 id={titleId} className={styles.lineupTitle}>
        {copy.preferencePrices}
      </h4>
      <ul aria-live="polite">
        {prices.map((row) => (
          <li key={row.key}>
            <strong>{row.label}</strong>
            <span>
              {row.status === "priced"
                ? copy.priceAmount(price.format(row.cost))
                : (row.detail ?? statuses[row.status])}
              {row.ceiling !== undefined &&
                ` · ${copy.priceCeiling(price.format(row.ceiling / 10))}`}
            </span>
            {row.status === "priced" && row.aboveCeiling && (
              <span className={styles.muted}>{copy.priceAboveCeiling}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PlanResult({
  title,
  state,
  squad,
  baseline,
  conflict,
  conflictMessage,
  diagnosis,
  prices = [],
  onRevise,
  reviseDisabled,
}: {
  title: string;
  state: ComputePhase;
  squad: EntrySquad;
  baseline?: EntryAdvice;
  conflict?: boolean;
  conflictMessage?: string;
  diagnosis?: ReactNode;
  prices?: PreferencePrice[];
  onRevise?: () => void;
  reviseDisabled?: boolean;
}) {
  const { language, locale, messages } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const computeCopy = COMPUTE_COPY[language];
  if (conflict || state.phase !== "done") {
    const message = conflict
      ? (conflictMessage ?? copy.variantConflict)
      : state.phase === "failed" || state.phase === "unavailable"
        ? failureSentence(
            computeCopy,
            state.reason,
            state.phase === "failed" ? state.retryAfterSeconds : null,
          )
        : state.phase === "waiting"
          ? (jobStanding(computeCopy, state) ?? copy.computing)
          : state.phase === "idle"
            ? copy.resultUnavailable
            : copy.computing;
    return (
      <article className={styles.result}>
        <h3 className={styles.resultTitle}>{title}</h3>
        {diagnosis ?? <p role="status">{message}</p>}
        <PreferencePrices prices={prices} />
      </article>
    );
  }
  const plan = state.envelope.payload;
  const multiweek = plan.window > 1;
  const weeks = multiweek ? plannedWeeks(plan) : null;
  const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek);
  const baselineWeek = baseline?.plan_weeks?.find((row) => row.gameweek === baseline.gameweek);
  const net = expectedNet(plan);
  const reference = baseline ? expectedNet(baseline) : null;
  const hits = plan.transfer_hit_points ?? week?.transfer_hit_points;
  const totalHits = weeks?.reduce((sum, row) => sum + row.transfer_hit_points, 0);
  const bank = plan.bank_after_tenths;
  const freeTransfers = plan.free_transfers_after ?? week?.free_transfers_after;
  const baselineHits = baseline?.transfer_hit_points ?? baselineWeek?.transfer_hit_points;
  const baselineTotalHits =
    baseline && plannedWeeks(baseline)?.reduce((sum, row) => sum + row.transfer_hit_points, 0);
  const baselineBank = baseline?.bank_after_tenths;
  const baselineFreeTransfers =
    baseline?.free_transfers_after ?? baselineWeek?.free_transfers_after;
  const pointDelta = (value: number | undefined, original: number | undefined, digits = 0) =>
    value === undefined || original === undefined || value === original
      ? undefined
      : signedPoints(value - original, digits, locale);
  const bankDelta =
    bank === undefined || baselineBank === undefined || bank === baselineBank
      ? undefined
      : `${bank > baselineBank ? "+" : ""}${money(bank - baselineBank, locale)}`;
  const chip = plan.chip ? messages.leagueMembers.chipNames[plan.chip] : null;
  const moves = plan.moves.filter((move) => move.player_in || move.player_out);

  return (
    <article className={styles.result} data-plan-ready="">
      <h3 className={styles.resultTitle}>{title}</h3>
      {onRevise && (
        <button
          className={styles.revise}
          disabled={reviseDisabled}
          type="button"
          onClick={onRevise}
        >
          {copy.revisePlan}
        </button>
      )}
      <dl className={styles.figures}>
        {chip && (
          <div>
            <dt>{messages.leagueMembers.chipLabel}</dt>
            <dd>{chip}</dd>
          </div>
        )}
        <div>
          <dt>{multiweek ? copy.totalNet : copy.net}</dt>
          <dd>{net === null ? "—" : points(net, 1, locale)}</dd>
        </div>
        {reference !== null && net !== null && (
          <div>
            <dt>{copy.difference}</dt>
            <dd>{signedPoints(net - reference, 1, locale)}</dd>
          </div>
        )}
        {multiweek && week && (
          <div>
            <dt>{copy.currentNet}</dt>
            <dd>
              {points(weekNet(week), 1, locale)}
              <MetricDelta
                label={copy.difference}
                value={pointDelta(weekNet(week), baselineWeek && weekNet(baselineWeek), 1)}
              />
            </dd>
          </div>
        )}
        {multiweek && (
          <div>
            <dt>{copy.totalHits}</dt>
            <dd>
              {totalHits === undefined ? "—" : points(totalHits, 0, locale)}
              <MetricDelta
                label={copy.difference}
                value={pointDelta(totalHits, baselineTotalHits)}
              />
            </dd>
          </div>
        )}
        <div>
          <dt>{copy.hits}</dt>
          <dd>
            {hits === undefined ? "—" : points(hits, 0, locale)}
            <MetricDelta label={copy.difference} value={pointDelta(hits, baselineHits)} />
          </dd>
        </div>
        <div>
          <dt>{multiweek ? copy.currentBank : copy.bank}</dt>
          <dd>
            {bank === undefined ? "—" : money(bank, locale)}
            <MetricDelta label={copy.difference} value={bankDelta} />
          </dd>
        </div>
        <div>
          <dt>{copy.transfers}</dt>
          <dd>
            {freeTransfers ?? "—"}
            <MetricDelta
              label={copy.difference}
              value={pointDelta(freeTransfers, baselineFreeTransfers)}
            />
          </dd>
        </div>
      </dl>
      <PreferencePrices prices={prices} />
      <PlanSquad plan={plan} squad={squad} />
      {moves.length ? (
        <ul className={styles.moves}>
          {moves.map(({ move_id, player_in, player_out }) => (
            <li key={move_id}>
              {player_out?.name ?? "—"} → <strong>{player_in?.name ?? "—"}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p>{copy.hold}</p>
      )}
      {weeks && <UpcomingWeeks weeks={weeks.slice(1)} />}
    </article>
  );
}
