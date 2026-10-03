/** The league the visitor opened by its number; nothing under /league renders without one. */
import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "squadopt.league";
const CHANGE_EVENT = "squadopt:league-changed";

function readStored(): number | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const id = Number(raw);
    return Number.isSafeInteger(id) && id > 0 ? id : null;
  } catch {
    // Browser storage is optional; without it the league is asked for on every visit.
    return null;
  }
}

let chosenLeagueId: number | null = readStored();

export function readChosenLeague(): number | null {
  return chosenLeagueId;
}

export function writeChosenLeague(leagueId: number | null): void {
  chosenLeagueId =
    leagueId !== null && Number.isSafeInteger(leagueId) && leagueId > 0 ? leagueId : null;
  try {
    if (chosenLeagueId === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, String(chosenLeagueId));
  } catch {
    // The in-memory choice still carries this visit.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

function snapshot(): number | null {
  return chosenLeagueId;
}

export function useChosenLeague(): {
  leagueId: number | null;
  choose: (leagueId: number) => void;
  forget: () => void;
} {
  const leagueId = useSyncExternalStore(subscribe, snapshot, () => null);
  const choose = useCallback((id: number) => writeChosenLeague(id), []);
  const forget = useCallback(() => writeChosenLeague(null), []);
  return { leagueId, choose, forget };
}
