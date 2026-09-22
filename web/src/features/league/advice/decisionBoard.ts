import type { EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { AdviceRequest } from "./adviceClient";
import { adviceRequestKey } from "./adviceJobStore";
import { checkedAdvice } from "./adviceResponse";

export interface DecisionCandidate {
  id: string;
  request: AdviceRequest;
  envelope: LeagueViewEnvelope<EntryAdvice>;
}

export interface DecisionBoardState {
  candidates: DecisionCandidate[];
  preferred: string | null;
  note: string;
}

export const emptyBoard = (): DecisionBoardState => ({ candidates: [], preferred: null, note: "" });

/** Never pin the old baseline displayed while another question is being computed. */
export function decisionCandidate(
  envelope: unknown,
  request: AdviceRequest,
  squad: LeagueViewEnvelope<EntrySquad>,
): DecisionCandidate | null {
  try {
    const context = squad.payload;
    const explicit: AdviceRequest = {
      ...request,
      model: request.model ?? "current",
      top100Weight: request.top100Weight ?? 0,
      managersWord: request.managersWord ?? false,
      chip: request.chip ?? null,
      season: context.season,
      gameweek: context.gameweek,
    };
    const checked = checkedAdvice(envelope, explicit);
    const p = checked.payload;
    if (
      !context.source_snapshot_id ||
      p.source_snapshot_id !== context.source_snapshot_id ||
      p.league_id !== context.league_id ||
      p.entry_id !== context.entry.entry_id ||
      p.squad_basis !== context.squad_basis ||
      checked.source_kind !== squad.source_kind ||
      !["OPTIMAL", "FEASIBLE"].includes(p.solver_status ?? "") ||
      p.starting_xi?.length !== 11 ||
      p.bench?.length !== 4 ||
      !p.captain ||
      !p.vice_captain ||
      !Number.isFinite(p.expected_own_points)
    )
      return null;
    return { id: adviceRequestKey(explicit), request: explicit, envelope: checked };
  } catch {
    return null;
  }
}

/** Points are gross in the contract; missing hit evidence is never silently zero. */
export function decisionMetrics(p: EntryAdvice) {
  const hits = p.transfer_hit_points;
  const net =
    typeof p.expected_own_points === "number" && typeof hits === "number"
      ? p.expected_own_points - hits
      : null;
  const gain =
    typeof p.expected_gain_vs_hold === "number" && typeof hits === "number"
      ? p.expected_gain_vs_hold - hits
      : null;
  const weeks = p.plan_weeks;
  const complete =
    weeks?.length === p.window &&
    weeks.every(
      (week, i) =>
        week.gameweek === p.gameweek + i &&
        Number.isFinite(week.expected_points) &&
        Number.isFinite(week.transfer_hit_points),
    );
  return {
    net,
    gain,
    horizonNet:
      p.window === 1
        ? net
        : complete
          ? weeks.reduce((sum, week) => sum + week.expected_points - week.transfer_hit_points, 0)
          : null,
    horizonHits:
      p.window === 1
        ? (hits ?? null)
        : complete
          ? weeks.reduce((sum, week) => sum + week.transfer_hit_points, 0)
          : null,
    remainingTransfers: complete ? weeks.at(-1)!.free_transfers_after : null,
  };
}

const storageKey = (squad: LeagueViewEnvelope<EntrySquad>) =>
  `squadopt.decision-board:${squad.payload.league_id}:${squad.payload.entry.entry_id}`;

export function loadDecisionBoard(squad: LeagueViewEnvelope<EntrySquad>): DecisionBoardState {
  try {
    const raw = JSON.parse(sessionStorage.getItem(storageKey(squad)) ?? "null");
    // Includes the capture, roster, bank, transfer rights, squad basis and publication.
    if (!raw || raw.context !== JSON.stringify(squad) || !Array.isArray(raw.candidates))
      return emptyBoard();
    const candidates: DecisionCandidate[] = [];
    for (const saved of raw.candidates.slice(0, 3)) {
      if (!saved?.request) continue;
      const candidate = decisionCandidate(saved.envelope, saved.request, squad);
      if (candidate && !candidates.some((c) => c.id === candidate.id)) candidates.push(candidate);
    }
    return {
      candidates,
      preferred: candidates.some((c) => c.id === raw.preferred) ? raw.preferred : null,
      note: typeof raw.note === "string" ? raw.note.slice(0, 500) : "",
    };
  } catch {
    return emptyBoard();
  }
}

export function saveDecisionBoard(
  squad: LeagueViewEnvelope<EntrySquad>,
  board: DecisionBoardState,
): boolean {
  try {
    sessionStorage.setItem(
      storageKey(squad),
      JSON.stringify({ ...board, context: JSON.stringify(squad) }),
    );
    return true;
  } catch {
    return false;
  }
}

/** Reopen settings only; no automatic job, transfer or chip activation. */
export function decisionParams(current: URLSearchParams, r: AdviceRequest): URLSearchParams {
  const next = new URLSearchParams(current);
  for (const key of ["mode", "window", "rival", "model", "top100", "llm", "chip"]) next.delete(key);
  next.set("mode", r.strategy);
  next.set("window", String(r.window));
  if (r.rivalEntryId != null) next.set("rival", String(r.rivalEntryId));
  if (r.model === "football") next.set("model", "football");
  if (r.top100Weight) next.set("top100", String(r.top100Weight));
  if (r.managersWord) next.set("llm", "on");
  if (r.chip) next.set("chip", r.chip);
  return next;
}
