/**
 * The heading's light, as the board drawn below it says: whether one of the member's own rows
 * is in a match being played, and the read whose arrival it breathes for. The board sets it and
 * the heading reads it, so only the light is drawn again when it changes.
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

export function createLiveLight(): LiveLight {
  let state: LightState | null = null;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set: (next) => {
      if (
        next === state ||
        (next !== null &&
          state !== null &&
          next.entryId === state.entryId &&
          next.playing === state.playing &&
          next.breath === state.breath)
      ) {
        return;
      }
      state = next;
      for (const listener of listeners) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
