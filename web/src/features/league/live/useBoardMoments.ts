/**
 * The GOL board's batches for the member page: each read's goals, assists and cards from the
 * live week, and the automatic substitutions a read adds (`newSubstitutions`), numbered as one
 * stream. Every first read the live score makes (`MemberLive.start`: the member's week opened,
 * a tool's page left) is a starting point for substitutions, as it is for its goals.
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
  /** The member and week the substitutions belong to, and the live score's first read. */
  week: string | null;
  start: number | null;
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
    start: null,
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
  if (
    shown !== null &&
    (read !== seen.read ||
      momentsId !== seen.moments ||
      week !== seen.week ||
      live.start !== seen.start)
  ) {
    const items: BoardMoment[] = [];
    if (live.moments !== null && momentsId !== seen.moments) items.push(...live.moments.items);
    const { seen: substitutions, fresh } = newSubstitutions(
      week === seen.week && live.start === seen.start ? seen.substitutions : null,
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
      start: live.start,
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
 * line goes). While `waiting`, a page shows the read from before the board's first moment, and
 * `brought` is what the moments that have landed since then brought to its score; once the last
 * lands, the page takes the newest read whole. Under reduced motion nothing waits.
 */
export function useBoardHold(batch: BoardBatch | null): {
  brought: number;
  waiting: boolean;
  landed: (key: string) => void;
} {
  const [state, setState] = useState<{
    batch: number | null;
    pending: Map<string, number>;
    brought: number;
  }>({ batch: null, pending: new Map(), brought: 0 });
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
    setState({ batch: batch.id, pending, brought: pending.size === 0 ? 0 : state.brought });
  }
  const landed = useCallback(
    (key: string) =>
      setState((current) => {
        if (!current.pending.has(key)) return current;
        const pending = new Map(current.pending);
        const points = pending.get(key) ?? 0;
        pending.delete(key);
        // The last moment landed: the page takes the newest read whole.
        return { ...current, pending, brought: pending.size === 0 ? 0 : current.brought + points };
      }),
    [],
  );
  return { brought: state.brought, waiting: state.pending.size > 0, landed };
}

/**
 * The read a page draws: the newest, or while the board waits (`useBoardHold`) the one from
 * before its first moment, so the card, the pitch and the rows all wait together.
 */
export function useSettledRead<T extends { gameweek: number }>(
  read: T | null,
  waiting: boolean,
): T | null {
  const [settled, setSettled] = useState(read);
  if (!waiting && read !== settled) setSettled(read);
  return waiting && settled !== null && read !== null && settled.gameweek === read.gameweek
    ? settled
    : read;
}
