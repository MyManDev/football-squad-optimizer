/**
 * The GOL board's batches for the member page: each read's goals, assists and cards from the
 * live week, and the automatic substitutions a read adds (`newSubstitutions`), numbered as one
 * stream. The first read of a member's week is a starting point for substitutions, as it is
 * for goals.
 */

import { useCallback, useState } from "react";

import { prefersReducedMotion } from "../../../design/motion";

import { newSubstitutions, type BoardMoment } from "../../liveScore/boardMoments";
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
 * The points the board still has to bring to the live score: each queued moment's, from the
 * read that brought it until its run lands (`landed`). Under reduced motion nothing is held.
 */
export function useBoardHold(batch: BoardBatch | null): {
  held: number;
  landed: (key: string) => void;
} {
  const [state, setState] = useState<{ batch: number | null; pending: Map<string, number> }>({
    batch: null,
    pending: new Map(),
  });
  if (batch !== null && batch.id !== state.batch) {
    const pending = new Map(state.pending);
    if (!prefersReducedMotion()) {
      for (const moment of batch.items) {
        if (moment.kind === "substitution" || moment.multiplier === 0) continue;
        if (moment.points !== null && moment.points !== 0) pending.set(moment.key, moment.points);
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
  return { held, landed };
}
