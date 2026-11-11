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
    const next: Seen = {
      week,
      start: live.start,
      substitutions,
      moments: momentsId,
      read,
      count,
      batch: items.length > 0 ? { id: count, items } : seen.batch,
    };
    setSeen(next);
    // The read's batch in this very render, so the hooks after this one (the hold, the read a
    // page draws) take it with the read that brought it, never the read alone.
    return next.batch;
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
  const [state, setState] = useState<Hold>({ batch: null, pending: new Map(), brought: 0 });
  // The hold as this render has it: a new batch's moments wait from the render that brings
  // them, so a read drawn beside them (`useSettledRead`) is held from its first render.
  let current = state;
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
    current = { batch: batch.id, pending, brought: pending.size === 0 ? 0 : state.brought };
    setState(current);
  }
  const landed = useCallback(
    (key: string) =>
      setState((held) => {
        if (!held.pending.has(key)) return held;
        const pending = new Map(held.pending);
        const points = pending.get(key) ?? 0;
        pending.delete(key);
        // The last moment landed: the page takes the newest read whole.
        return { ...held, pending, brought: pending.size === 0 ? 0 : held.brought + points };
      }),
    [],
  );
  return { brought: current.brought, waiting: current.pending.size > 0, landed };
}

interface Hold {
  /** The last batch taken. */
  batch: number | null;
  /** Each moment the board has still to play out, with the points it brings. */
  pending: Map<string, number>;
  brought: number;
}

/**
 * The read a page draws: the newest, or while the board waits (`useBoardHold`) the one from
 * before its first moment, so the card, the pitch and the rows all wait together. Only a read is
 * kept: a refused one (null) leaves the last read to hold under the next board. `owner` names
 * whose reads they are (the member), so one member's read is never drawn on another's page.
 */
export function useSettledRead<T extends { gameweek: number }>(
  read: T | null,
  waiting: boolean,
  owner: string,
): T | null {
  const [settled, setSettled] = useState<{ owner: string; read: T } | null>(
    read === null ? null : { owner, read },
  );
  if (!waiting && read !== null && (settled?.read !== read || settled.owner !== owner)) {
    setSettled({ owner, read });
  }
  const held =
    settled !== null &&
    settled.owner === owner &&
    read !== null &&
    settled.read.gameweek === read.gameweek
      ? settled.read
      : null;
  return waiting && held !== null ? held : read;
}
