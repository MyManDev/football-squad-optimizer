import type { ComputePhase } from "../advice/useAdviceJob";
import type { EntryAdvice } from "../types";

export function expectedNet(plan: EntryAdvice) {
  const week = plan.plan_weeks?.find((row) => row.gameweek === plan.gameweek);
  if (week) return week.expected_points - week.transfer_hit_points;
  if (plan.lineup_expectation) return plan.lineup_expectation.expected_net_points;
  return plan.expected_own_points != null && plan.transfer_hit_points != null
    ? plan.expected_own_points - plan.transfer_hit_points
    : null;
}

function action(plan: EntryAdvice) {
  return JSON.stringify([
    plan.moves
      .map(({ player_in, player_out }) => [player_out?.player_id, player_in?.player_id].join(":"))
      .sort(),
    plan.starting_xi?.map(({ player_id }) => player_id).sort((a, b) => a - b),
    plan.bench?.map(({ player_id }) => player_id),
    plan.captain?.player_id,
    plan.vice_captain?.player_id,
    plan.chip ?? null,
  ]);
}

export function samePlan(first: ComputePhase, second: ComputePhase) {
  return (
    first.phase === "done" &&
    second.phase === "done" &&
    first.envelope.payload.starting_xi != null &&
    second.envelope.payload.starting_xi != null &&
    action(first.envelope.payload) === action(second.envelope.payload)
  );
}
