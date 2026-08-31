/**
 * Who is looking at the league — as a claim, deliberately not an identity.
 *
 * The FPL entry id is already a public identifier: post-deadline squads, ranks and
 * points are visible to anyone, so no authentication is needed to show them. What a
 * viewer selects here is therefore an *assertion* ("this row is me"), stored only in
 * their own browser, and the page says so in so many words. Anyone can select anyone,
 * and that is fine precisely because nothing shown is private.
 *
 * The seam is the point: `verified: false, source: "self-selected"` today; an
 * authenticated future returns `verified: true, source: "auth"` from the same hook,
 * and nothing else changes — the copy and the privacy rule change, the data path
 * does not.
 */

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "squadopt.viewer";
const CHANGE_EVENT = "squadopt:viewer-changed";

export interface ViewerEntry {
  entryId: number;
  verified: false;
  source: "self-selected";
}

export function readViewerEntry(): ViewerEntry | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "entryId" in parsed &&
      typeof (parsed as { entryId: unknown }).entryId === "number" &&
      Number.isInteger((parsed as { entryId: number }).entryId) &&
      (parsed as { entryId: number }).entryId > 0
    ) {
      return {
        entryId: (parsed as { entryId: number }).entryId,
        verified: false,
        source: "self-selected",
      };
    }
    return null;
  } catch {
    // A blocked or corrupted store reads as "nobody selected", never as an error.
    return null;
  }
}

function writeViewerEntry(entryId: number | null): void {
  try {
    if (entryId === null) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ entryId }));
    }
  } catch {
    // Selection is a convenience; a browser that refuses storage refuses quietly.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(CHANGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function snapshot(): number | null {
  return readViewerEntry()?.entryId ?? null;
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
