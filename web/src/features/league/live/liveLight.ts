/**
 * The heading's light, as the board drawn below it says: whether one of the member's own rows
 * is in a match being played, and the read whose arrival it breathes for. The board sets it and
 * the heading reads it, so only the light is drawn again when it changes. A read breathes once
 * at most: once its breath is offered, lit or not, the light coming on again for it (the follow
 * window closing and opening again on the same board) stands still.
 */

export interface LightState {
  entryId: number;
  playing: boolean;
  /** The newer read the light breathes three times for, or null to stand still. */
  breath: string | null;
}

export interface LiveLight {
  get: () => LightState | null;
  set: (state: LightState | null) => void;
  subscribe: (listener: () => void) => () => void;
}

const same = (a: LightState | null, b: LightState | null) =>
  a === b ||
  (a !== null &&
    b !== null &&
    a.entryId === b.entryId &&
    a.playing === b.playing &&
    a.breath === b.breath);

export function createLiveLight(): LiveLight {
  let state: LightState | null = null;
  const breathed = new Set<string>();
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set: (wanted) => {
      const again =
        wanted !== null &&
        wanted.playing &&
        wanted.breath !== null &&
        breathed.has(wanted.breath) &&
        !(state !== null && state.playing && state.breath === wanted.breath);
      const next = again ? { ...wanted, breath: null } : wanted;
      if (same(next, state)) return;
      state = next;
      // Offered, a read's breath is spent, lit or not: the light never breathes for it later.
      if (next !== null && next.breath !== null) breathed.add(next.breath);
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
