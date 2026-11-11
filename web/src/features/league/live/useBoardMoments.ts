/**
 * The GOL board's batches for the member page: each read's goals, assists and cards from the
 * live week, and the automatic substitutions a read adds (`newSubstitutions`), numbered as one
 * stream. The first read of a member's week is a starting point for substitutions, as it is
 * for goals.
 */

import { useCallback, useState } from "react";

import { prefersReducedMotion } from "../../../design/motion";

import { newSubstitutions, shownOnBoard, type BoardMoment } from "../../liveScore/boardMoments";
import type { MemberLive } from "./useMemberLiveScore";

export interface BoardBatch {
  id: number;
  items: BoardMoment[];
}

interface Seen {
  /** The member and week the substitutions belong to. */
  week: string | null;
  substitutions: ReadonlySet<string> | null;
  /** The last moments batch taken, and the last read's time. */
  moments: number | null;
  read: string | null;
  count: number;
  batch: BoardBatch | null;
}

export function useBoardMoments(live: MemberLive, entryId: number): BoardBatch | null {
  const [seen, setSeen] = useState<Seen>({
    week: null,
    substitutions: null,
    moments: null,
    read: null,
    count: 0,
    batch: null,
  });
  const shown = live.shown;
  const week = shown === null ? null : `${entryId}:${shown.gameweek}`;
  const read = shown === null ? null : shown.score.source_time;
  const momentsId = live.moments?.id ?? null;
  if (shown !== null && (read !== seen.read || momentsId !== seen.moments || week !== seen.week)) {
    const items: BoardMoment[] = [];
    if (live.moments !== null && momentsId !== seen.moments) items.push(...live.moments.items);
    const { seen: substitutions, fresh } = newSubstitutions(
      week === seen.week ? seen.substitutions : null,
      shown.score.autosubs,
    );
    for (const [out, incoming] of fresh) {
      items.push({
        key: `sub:${read}:${out}:${incoming}`,
        kind: "substitution",
        size: "big",
        out: shown.names.get(out) ?? "",
        in: shown.names.get(incoming) ?? "",
      });
    }
    const count = items.length > 0 ? seen.count + 1 : seen.count;
    setSeen({
      week,
      substitutions,
      moments: momentsId,
      read,
      count,
      batch: items.length > 0 ? { id: count, items } : seen.batch,
    });
  }
  return seen.batch;
}

/**
 * What the board has still to play out: each moment it shows, from the read that brought it
 * until it lands (`landed`: a goal's run reaches the score, a substitution's board or a card's
 * line goes). `held` is the points still on their way to the live score; `waiting` says some
 * moment has still to land. Under reduced motion nothing is held.
 */
export function useBoardHold(batch: BoardBatch | null): {
  held: number;
  waiting: boolean;
  landed: (key: string) => void;
} {
  const [state, setState] = useState<{ batch: number | null; pending: Map<string, number> }>({
    batch: null,
    pending: new Map(),
  });
  if (batch !== null && batch.id !== state.batch) {
    // Under reduced motion the layer drops its queue for one still line, so what it held from
    // earlier moments goes with it: nothing is left waiting for a board that will not play.
    const still = prefersReducedMotion();
    const pending = still ? new Map<string, number>() : new Map(state.pending);
    if (!still) {
      // The moments the board plays (shownOnBoard), each with the points it brings, if any.
      for (const moment of batch.items) {
        if (!shownOnBoard(moment)) continue;
        pending.set(moment.key, moment.kind === "substitution" ? 0 : (moment.points ?? 0));
      }
    }
    setState({ batch: batch.id, pending });
  }
  const landed = useCallback(
    (key: string) =>
      setState((current) => {
        if (!current.pending.has(key)) return current;
        const pending = new Map(current.pending);
        pending.delete(key);
        return { ...current, pending };
      }),
    [],
  );
  let held = 0;
  for (const points of state.pending.values()) held += points;
  return { held, waiting: state.pending.size > 0, landed };
}
