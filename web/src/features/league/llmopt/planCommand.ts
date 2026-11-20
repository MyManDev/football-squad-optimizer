import type { EntryAdvice } from "../types";
import type { CatalogPlayer, PlanDraft } from "./intent";
import type { PlanCommand, PlanContext } from "./planHistory";
import { plannedWeeks } from "./planComparison";
import { summarizeRevision } from "./planRevision";

export function commandDraft(
  command: PlanCommand,
  catalogue: PlanContext | undefined,
  plan: EntryAdvice | undefined,
  draft: PlanDraft,
  players: CatalogPlayer[],
) {
  if (!catalogue?.plans.some((p) => p.plan_id === command.plan_id) || !plan)
    throw new Error("Unknown plan");
  const reference = summarizeRevision(plan);
  if (!reference) throw new Error("Incomplete plan");
  const action = command.action;
  const expected = [
    "plan_id",
    "action",
    ...(action !== "select" ? ["week"] : []),
    ...(["freeze_transfer", "substitute"].includes(action) ? ["player_id"] : []),
    ...(action === "substitute" ? ["replacement_id"] : []),
  ].sort();
  if (Object.keys(command).sort().join() !== expected.join())
    throw new Error("Unexpected command fields");
  if (action === "select") return { reference };
  const week = command.week;
  if (week === undefined || !Number.isInteger(week) || week < 1 || week > reference.weeks.length)
    throw new Error("Unknown week");
  if (action === "freeze_week")
    return {
      reference,
      draft: {
        ...draft,
        window: plan.window as 1 | 3,
        keep_weeks: [...new Set([...(draft.keep_weeks ?? []), week])].sort() as (1 | 2 | 3)[],
      },
    };
  const player = command.player_id;
  const w = reference.weeks[week - 1]!;
  if (action === "freeze_transfer") {
    if (!w.incoming.some((p) => p.player_id === player)) throw new Error("Unknown incoming player");
    const pair =
      week === 1 ? plan.moves.find((m) => m.player_in?.player_id === player)?.player_out : null;
    const incoming = players.find((p) => p.id === player);
    const outgoing =
      pair?.player_id ?? (w.outgoing.length === 1 ? w.outgoing[0]?.player_id : undefined);
    if (!incoming || outgoing === undefined) throw new Error("Ambiguous transfer");
    return {
      reference,
      draft: {
        ...draft,
        window: plan.window as 1 | 3,
        hard: [
          ...draft.hard,
          { kind: "buy_player" as const, player_id: incoming.id, week },
          { kind: "avoid_player" as const, player_id: outgoing, week },
        ],
      },
    };
  }
  if (action !== "substitute") throw new Error("Unknown action");
  const row = plannedWeeks(plan)?.[week - 1];
  const lineup = row?.lineup ?? (week === 1 ? plan : undefined);
  const squad = [...(lineup?.starting_xi ?? []), ...(lineup?.bench ?? [])];
  if (
    !squad.some((p) => p.player_id === player) ||
    squad.some((p) => p.player_id === command.replacement_id) ||
    !players.some((p) => p.id === command.replacement_id)
  )
    throw new Error("Unknown substitution");
  return {
    reference: { ...reference, compareOnly: true as const },
    draft: {
      ...draft,
      window: plan.window as 1 | 3,
      hard: [
        ...draft.hard.filter(
          (r) =>
            !(
              "player_id" in r &&
              r.player_id === player &&
              ["keep_player", "include_player", "buy_player"].includes(r.kind) &&
              (r.week === undefined || r.week === week)
            ),
        ),
        { kind: "avoid_player" as const, player_id: player!, week },
        { kind: "include_player" as const, player_id: command.replacement_id!, week },
      ],
      comparison: undefined,
    },
  };
}
