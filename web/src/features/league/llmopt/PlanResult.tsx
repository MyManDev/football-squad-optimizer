import { money, points, signedPoints } from "../../../lib/format";
import { COMPUTE_COPY, failureSentence, jobStanding } from "../advice/computeCopy";
import type { ComputePhase } from "../advice/useAdviceJob";
import type { EntryAdvice } from "../types";
import { LLMOPT_COPY } from "./copy";
import { useLanguage } from "../../../i18n/context";
import { expectedNet } from "./planComparison";
import styles from "./LLMOptPage.module.css";

export function PlanResult({
  title,
  state,
  baseline,
  conflict,
}: {
  title: string;
  state: ComputePhase;
  baseline?: EntryAdvice;
  conflict?: boolean;
}) {
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const computeCopy = COMPUTE_COPY[language];
  if (conflict || state.phase !== "done") {
    const message = conflict
      ? copy.variantConflict
      : state.phase === "failed" || state.phase === "unavailable"
        ? failureSentence(
            computeCopy,
            state.reason,
            state.phase === "failed" ? state.retryAfterSeconds : null,
          )
        : state.phase === "waiting"
          ? (jobStanding(computeCopy, state) ?? copy.computing)
          : copy.computing;
    return (
      <article className={styles.result}>
        <h3>{title}</h3>
        <p role="status">{message}</p>
      </article>
    );
  }
  const plan = state.envelope.payload;
  const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek);
  const net = expectedNet(plan);
  const reference = baseline ? expectedNet(baseline) : null;
  const hits = plan.transfer_hit_points ?? week?.transfer_hit_points;
  const bank = plan.bank_after_tenths;
  const freeTransfers = plan.free_transfers_after ?? week?.free_transfers_after;
  const moves = plan.moves.filter((move) => move.player_in || move.player_out);

  return (
    <article className={styles.result} data-plan-ready="">
      <h3>{title}</h3>
      <dl className={styles.figures}>
        <div>
          <dt>{copy.net}</dt>
          <dd>{net === null ? "—" : points(net, 1, locale)}</dd>
        </div>
        {reference !== null && net !== null && (
          <div>
            <dt>{copy.difference}</dt>
            <dd>{signedPoints(net - reference, 1, locale)}</dd>
          </div>
        )}
        <div>
          <dt>{copy.hits}</dt>
          <dd>{hits === undefined ? "—" : points(hits, 0, locale)}</dd>
        </div>
        <div>
          <dt>{copy.bank}</dt>
          <dd>{bank === undefined ? "—" : money(bank, locale)}</dd>
        </div>
        <div>
          <dt>{copy.transfers}</dt>
          <dd>{freeTransfers ?? "—"}</dd>
        </div>
      </dl>
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
      {plan.captain && (
        <p>
          {copy.captain} · <strong>{plan.captain.name}</strong>
        </p>
      )}
      {plan.vice_captain && (
        <p>
          {copy.vice} · <strong>{plan.vice_captain.name}</strong>
        </p>
      )}
      {plan.starting_xi?.length ? (
        <details>
          <summary>{copy.lineup}</summary>
          <p>{plan.starting_xi.map(({ name }) => name).join(", ")}</p>
          {plan.bench?.length ? (
            <p>
              {copy.bench} · {plan.bench.map(({ name }) => name).join(", ")}
            </p>
          ) : null}
        </details>
      ) : null}
      {plan.solver_status === "FEASIBLE" && <p className={styles.muted}>{copy.notProven}</p>}
    </article>
  );
}
