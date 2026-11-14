import { useId } from "react";

import { useLanguage } from "../../../i18n/context";
import { clubCodesFromFixtures } from "../../../lib/clubs";
import { money, points, signedPoints } from "../../../lib/format";
import { useFixtures } from "../../fixtures/data";
import { COMPUTE_COPY, failureSentence, jobStanding } from "../advice/computeCopy";
import type { ComputePhase } from "../advice/useAdviceJob";
import { MemberBench, MemberPitch } from "../components/MemberPitch";
import { squadOnPitch } from "../pages/squadOnPitch";
import type { EntryAdvice, EntrySquad } from "../types";
import { LLMOPT_COPY } from "./copy";
import { expectedNet } from "./planComparison";
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

export function PlanResult({
  title,
  state,
  squad,
  baseline,
  conflict,
}: {
  title: string;
  state: ComputePhase;
  squad: EntrySquad;
  baseline?: EntryAdvice;
  conflict?: boolean;
}) {
  const { language, locale, messages } = useLanguage();
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
        <h3 className={styles.resultTitle}>{title}</h3>
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
  const chip = plan.chip ? messages.leagueMembers.chipNames[plan.chip] : null;
  const moves = plan.moves.filter((move) => move.player_in || move.player_out);

  return (
    <article className={styles.result} data-plan-ready="">
      <h3 className={styles.resultTitle}>{title}</h3>
      <dl className={styles.figures}>
        {chip && (
          <div>
            <dt>{messages.leagueMembers.chipLabel}</dt>
            <dd>{chip}</dd>
          </div>
        )}
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
      {plan.solver_status === "FEASIBLE" && <p className={styles.muted}>{copy.notProven}</p>}
    </article>
  );
}
