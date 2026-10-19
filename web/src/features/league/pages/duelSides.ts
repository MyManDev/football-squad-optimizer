import { rivalCandidates } from "../advice/adviceSelection";
import type { EntrySquad, EntrySquadPlayer, EntryView, LeagueViewEnvelope } from "../types";

/** One side of the duel: its eleven in the document's order, its captain and its total. */
export interface DuelSide {
  entryId: number;
  eleven: EntrySquadPlayer[];
  captain: EntrySquadPlayer;
  /** The eleven's expected points with the captain's counted twice. */
  total: number;
}

export interface Duel {
  member: DuelSide;
  rival: DuelSide;
  /** Players in both elevens; their points cancel. */
  shared: ReadonlySet<number>;
  /** The member's total minus the rival's. */
  difference: number;
  /** The part of the difference the players only one side starts make. */
  fromPlayers: number;
  /** The part the two armbands make: the member's captain's points minus the rival's. */
  fromCaptains: number;
}

function side(envelope: LeagueViewEnvelope<EntrySquad>): DuelSide | null {
  const eleven = envelope.payload.starting_xi;
  const ids = new Set(eleven.map((player) => player.player_id));
  const captains = eleven.filter((player) => player.is_captain);
  if (
    eleven.length !== 11 ||
    ids.size !== 11 ||
    captains.length !== 1 ||
    !eleven.every((player) => Number.isFinite(player.expected_points))
  )
    return null;
  const captain = captains[0]!;
  const total = eleven.reduce((sum, player) => sum + player.expected_points, 0);
  return {
    entryId: envelope.payload.entry.entry_id,
    eleven,
    captain,
    total: total + captain.expected_points,
  };
}

/** Whether a document's eleven can stand in a duel: eleven players, one captain, each with points. */
export function canDuel(envelope: LeagueViewEnvelope<EntrySquad>): boolean {
  return side(envelope) !== null;
}

/**
 * The member's held eleven against a rival's, from the two entry documents of one capture
 * (#1133). The difference is the elevens' expected points with each captain's counted
 * twice, the basis the device table uses; the players both start cancel, so it splits into
 * what the players only one side starts make and what the two armbands make. Documents from
 * different captures, a partial eleven, or an eleven without one captain give no duel.
 */
export function duelOf(
  member: LeagueViewEnvelope<EntrySquad>,
  rival: LeagueViewEnvelope<EntrySquad>,
): Duel | null {
  const own = member.payload;
  const other = rival.payload;
  if (
    own.entry.entry_id === other.entry.entry_id ||
    member.contract_version !== rival.contract_version ||
    member.source_kind !== rival.source_kind ||
    own.league_id !== other.league_id ||
    own.season !== other.season ||
    own.gameweek !== other.gameweek ||
    !own.source_snapshot_id ||
    own.source_snapshot_id !== other.source_snapshot_id
  )
    return null;
  const mine = side(member);
  const theirs = side(rival);
  if (!mine || !theirs) return null;
  const theirIds = new Set(theirs.eleven.map((player) => player.player_id));
  const shared = new Set(
    mine.eleven.map((player) => player.player_id).filter((id) => theirIds.has(id)),
  );
  const only = (eleven: EntrySquadPlayer[]) =>
    eleven
      .filter((player) => !shared.has(player.player_id))
      .reduce((sum, player) => sum + player.expected_points, 0);
  return {
    member: mine,
    rival: theirs,
    shared,
    difference: mine.total - theirs.total,
    fromPlayers: only(mine.eleven) - only(theirs.eleven),
    fromCaptains: mine.captain.expected_points - theirs.captain.expected_points,
  };
}

/**
 * The rival the duel sets beside the member, named by `?duel=`: one of the other human
 * members, or none for an id the member list does not hold.
 */
export function duelRivalId(
  searchParams: URLSearchParams,
  members: EntryView[],
  entryId: number,
): number | null {
  const named = Number(searchParams.get("duel"));
  return rivalCandidates(members, entryId).some((member) => member.entry_id === named)
    ? named
    : null;
}
