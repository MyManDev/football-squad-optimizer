/**
 * A public, self-selected member claim for this page visit only. The claim names the
 * league it was made in: a member of league A is nobody in league B.
 */
import { useCallback, useSyncExternalStore } from "react";

const CHANGE_EVENT = "squadopt:viewer-changed";
let selected: ViewerClaim | null = null;

// Discard selections left by versions that remembered the previous visit.
try {
  window.localStorage.removeItem("squadopt.viewer");
} catch {
  // Browser storage is optional; the current selection lives only in memory.
}

export interface ViewerClaim {
  leagueId: number;
  entryId: number;
}

export interface ViewerEntry extends ViewerClaim {
  verified: false;
  source: "self-selected";
}

function entry(claim: ViewerClaim | null): ViewerEntry | null {
  return claim === null ? null : { ...claim, verified: false, source: "self-selected" };
}

function positive(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

export function readViewerEntry(): ViewerEntry | null {
  return entry(selected);
}

export function writeViewerEntry(claim: ViewerClaim | null): void {
  selected =
    claim !== null && positive(claim.leagueId) && positive(claim.entryId)
      ? { leagueId: claim.leagueId, entryId: claim.entryId }
      : null;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

function snapshot(): ViewerClaim | null {
  return selected;
}

/**
 * The visitor's claim, and the ways to make or drop one. With a league, the claim is
 * the one made in that league (a claim made elsewhere is nobody here); without one, the
 * claim as made, league included.
 */
export function useViewerEntry(leagueId?: number): {
  viewer: ViewerEntry | null;
  select: (entryId: number) => void;
  clear: () => void;
} {
  const claim = useSyncExternalStore(subscribe, snapshot, () => null);
  const select = useCallback(
    (entryId: number) => {
      if (leagueId === undefined) throw new Error("A claim is made in a league.");
      writeViewerEntry({ leagueId, entryId });
    },
    [leagueId],
  );
  const clear = useCallback(() => writeViewerEntry(null), []);
  const own = claim !== null && (leagueId === undefined || claim.leagueId === leagueId);
  return { viewer: own ? entry(claim) : null, select, clear };
}
