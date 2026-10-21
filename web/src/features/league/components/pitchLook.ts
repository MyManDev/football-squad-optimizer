import { useCallback, useSyncExternalStore } from "react";

import { AA, contrastRatio } from "../../../design/contrastRatio";
import { CLUB_COLOURS } from "../../../lib/clubs";

/**
 * How the viewer likes the pitch drawn (#1136): the grass's pattern, and whether each plate
 * takes its club's colours. Like the sidebar's state, it is a convenience kept in this
 * browser only: it holds no entry, no plan and no language, it changes no figure, and an
 * unreadable or unknown value gives the default look (stripes, white plates). A change is
 * instant; nothing about it moves.
 */
export const PITCH_LOOK_STORAGE_KEY = "squadopt.pitchLook";

export const GRASS_LOOKS = ["stripes", "plain", "checks"] as const;
export type GrassLook = (typeof GRASS_LOOKS)[number];

export interface PitchLook {
  grass: GrassLook;
  clubColours: boolean;
}

export const DEFAULT_PITCH_LOOK: PitchLook = { grass: "stripes", clubColours: false };

function parse(raw: string | null): PitchLook {
  if (raw === null) return DEFAULT_PITCH_LOOK;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return DEFAULT_PITCH_LOOK;
    const { grass, clubColours } = value as Record<string, unknown>;
    return {
      grass: GRASS_LOOKS.includes(grass as GrassLook) ? (grass as GrassLook) : "stripes",
      clubColours: clubColours === true,
    };
  } catch {
    return DEFAULT_PITCH_LOOK;
  }
}

export function readPitchLook(): PitchLook {
  try {
    return parse(window.localStorage.getItem(PITCH_LOOK_STORAGE_KEY));
  } catch {
    return DEFAULT_PITCH_LOOK;
  }
}

// One look for every pitch on the page, so a change shows on each at once. It is read from
// storage once and kept here after, which also keeps a choice for the visit where storage
// cannot be written.
let current: PitchLook | null = null;
const listeners = new Set<() => void>();

function snapshot(): PitchLook {
  current ??= readPitchLook();
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function writePitchLook(look: PitchLook): void {
  current = look;
  try {
    window.localStorage.setItem(PITCH_LOOK_STORAGE_KEY, JSON.stringify(look));
  } catch {
    /* Storage may be unavailable; the pitch still follows the choice for this visit. */
  }
  for (const listener of listeners) listener();
}

/** Forget the kept look, so the next read comes from storage again. For tests. */
export function forgetPitchLook(): void {
  current = null;
}

export function usePitchLook(): [PitchLook, (change: Partial<PitchLook>) => void] {
  const look = useSyncExternalStore(subscribe, snapshot, () => DEFAULT_PITCH_LOOK);
  const change = useCallback(
    (patch: Partial<PitchLook>) => writePitchLook({ ...snapshot(), ...patch }),
    [],
  );
  return [look, change];
}

/** The ink and white a plate can print in; the colour-token test holds INK to tokens.css. */
export const PLATE_INK = "#10261a";
export const PLATE_WHITE = "#ffffff";

export interface ClubPlate {
  /** Which of the club's two colours the plate is filled with. */
  colour: "primary" | "secondary";
  fill: string;
  text: string;
}

/**
 * The colours a club's plate takes: its primary with ink or white, whichever reads better,
 * if that reaches 4.5:1; otherwise its secondary the same way. Every figure, name and code
 * on the plate is printed in that one text colour. A club with no colours, or with neither
 * colour readable, keeps the white plate (null).
 */
export function clubPlate(code: string | null | undefined): ClubPlate | null {
  const colours = code ? CLUB_COLOURS[code.toUpperCase()] : undefined;
  if (!colours) return null;
  for (const colour of ["primary", "secondary"] as const) {
    const fill = colours[colour];
    const text =
      contrastRatio(PLATE_INK, fill) >= contrastRatio(PLATE_WHITE, fill) ? PLATE_INK : PLATE_WHITE;
    if (contrastRatio(text, fill) >= AA) return { colour, fill, text };
  }
  return null;
}
