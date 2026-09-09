import type { AdvicePlayer, EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";

/** Published ID-set arithmetic; preserves source order and adds no projection or rank. */
export function comparedRivalPlayers(
  advice: LeagueViewEnvelope<EntryAdvice>,
  own: LeagueViewEnvelope<EntrySquad>,
  rival: LeagueViewEnvelope<EntrySquad> | null,
): { shared: AdvicePlayer[]; recommendedOnly: AdvicePlayer[]; rivalOnly: AdvicePlayer[] } | null {
  const plan = advice.payload;
  if (
    !rival ||
    !plan.source_snapshot_id ||
    !plan.starting_xi ||
    !plan.bench ||
    plan.entry_id !== own.payload.entry.entry_id ||
    plan.rival_entry_id !== rival.payload.entry.entry_id ||
    plan.rival_entry_id === plan.entry_id
  )
    return null;
  for (const squad of [own, rival]) {
    if (
      squad.contract_version !== advice.contract_version ||
      squad.source_kind !== advice.source_kind ||
      squad.payload.league_id !== plan.league_id ||
      squad.payload.season !== plan.season ||
      squad.payload.gameweek !== plan.gameweek ||
      squad.payload.source_snapshot_id !== plan.source_snapshot_id
    )
      return null;
  }
  const recommended = [...plan.starting_xi, ...plan.bench];
  const held = rival.payload.starting_xi;
  const valid = (players: AdvicePlayer[], size: number) =>
    players.length === size &&
    players.every(
      (player) =>
        Number.isSafeInteger(player.player_id) &&
        player.player_id > 0 &&
        typeof player.name === "string",
    ) &&
    new Set(players.map((player) => player.player_id)).size === size;
  if (
    !valid(plan.starting_xi, 11) ||
    !valid(plan.bench, 4) ||
    !valid(recommended, 15) ||
    !valid(held, 11)
  )
    return null;
  const recommendedIds = new Set(recommended.map((player) => player.player_id));
  const heldIds = new Set(held.map((player) => player.player_id));
  return {
    shared: recommended.filter((player) => heldIds.has(player.player_id)),
    recommendedOnly: recommended.filter((player) => !heldIds.has(player.player_id)),
    rivalOnly: held.filter((player) => !recommendedIds.has(player.player_id)),
  };
}
