/** A public, self-selected member claim for this page visit only. */
import { useCallback, useSyncExternalStore } from "react";

const CHANGE_EVENT = "squadopt:viewer-changed";
let selectedEntryId: number | null = null;

// Discard selections left by versions that remembered the previous visit.
try {
  window.localStorage.removeItem("squadopt.viewer");
} catch {
  // Browser storage is optional; the current selection lives only in memory.
}

export interface ViewerEntry {
  entryId: number;
  verified: false;
  source: "self-selected";
}

export function readViewerEntry(): ViewerEntry | null {
  return selectedEntryId === null
    ? null
    : { entryId: selectedEntryId, verified: false, source: "self-selected" };
}

export function writeViewerEntry(entryId: number | null): void {
  selectedEntryId = entryId !== null && Number.isInteger(entryId) && entryId > 0 ? entryId : null;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

function snapshot(): number | null {
  return selectedEntryId;
}

export function useViewerEntry(): {
  viewer: ViewerEntry | null;
  select: (entryId: number) => void;
  clear: () => void;
} {
  const entryId = useSyncExternalStore(subscribe, snapshot, () => null);
  const select = useCallback((id: number) => writeViewerEntry(id), []);
  const clear = useCallback(() => writeViewerEntry(null), []);
  return {
    viewer: entryId === null ? null : { entryId, verified: false, source: "self-selected" },
    select,
    clear,
  };
}
