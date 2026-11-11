/**
 * The GOL replay on the member page: the member's live week read once, then what the board shows
 * of it handed to the board one by one, `REPLAY_STEP_MS` apart, once the opening cover has gone:
 * the goals and assists of the picks the official scorer counts, then the automatic
 * substitutions it made. Only the address opens it (`?replay=1`); the page shows no word of it.
 * While it plays the page shows no moment of its own reads, so the two never mix.
 */

import { useEffect, useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import { shownOnBoard, type BoardMoment } from "../../liveScore/boardMoments";
import { liveMoments } from "../../liveScore/liveMoments";
import { REPLAY_START_MS, REPLAY_STEP_MS, replayEvents } from "../../liveScore/liveReplay";
import { useCoverGone } from "../../liveScore/openingCover";
import type { Position } from "../../liveScore/weekLive";
import { forwarder as siteForwarder } from "../forwarder/client";
import type { EntrySquad } from "../types";
import { useLeague } from "../useLeague";
import { memberLiveScore } from "./memberLiveScore";
import type { BoardBatch } from "./useBoardMoments";
import type { MemberLiveDependencies } from "./useMemberLiveScore";

export function useGoalReplay(
  squad: EntrySquad,
  fixtures: FixturesPayload | null,
  dependencies: MemberLiveDependencies = {},
  enabled = false,
): BoardBatch | null {
  const { tree } = useLeague();
  const coverGone = useCoverGone();
  const [batch, setBatch] = useState<BoardBatch | null>(null);
  const entryId = squad.entry.entry_id;
  const gameweek = squad.gameweek;
  const capture = squad.source_snapshot_id ?? null;
  const forwarder = dependencies.forwarder ?? siteForwarder;
  const loadTable = dependencies.loadTable;
  const running = enabled && coverGone && fixtures !== null;

  useEffect(() => {
    if (!running || fixtures === null) return undefined;
    const read = new AbortController();
    const timers: ReturnType<typeof setTimeout>[] = [];
    const play = async () => {
      const { signal } = read;
      const bundle = await forwarder.entryBundle(entryId, gameweek, { signal });
      if (signal.aborted || !bundle.ok || bundle.document.current_week === null) return;
      const member = bundle.document.current_week;
      if (!forwarder.liveActivity) return;
      const [live, table] = await Promise.all([
        forwarder.liveActivity(member.gameweek, { signal }),
        (loadTable ?? ((s: AbortSignal) => tree.devicePlan(capture, { signal: s })))(signal).then(
          (envelope) => envelope.payload,
          () => null,
        ),
      ]);
      if (signal.aborted || !live.ok || live.document.activity === null || table === null) return;
      const { week, activity } = live.document;
      const scored = memberLiveScore({ live: week, activity, member, table, fixtures });
      if (!scored.ok) return;
      const shown = scored.live;
      const fifteen = [...shown.lineup.starting_xi, ...shown.lineup.bench];
      const players = new Map<number, { name: string; team: string; position: Position }>();
      member.pick_order.forEach((elementId, index) => {
        const player = fifteen[index];
        if (player === undefined || player.position === "UNK") return;
        players.set(elementId, {
          name: shown.names.get(elementId) ?? player.short_name,
          team: player.team,
          position: player.position,
        });
      });
      const nameOf = (elementId: number) =>
        players.get(elementId)?.name ?? shown.names.get(elementId) ?? "";
      // One step for each moment the board shows: a pick the scorer does not count raises
      // nothing, so it takes no step of its own.
      const steps: BoardMoment[][] = replayEvents(activity, member.pick_order).map((event, index) =>
        liveMoments([event], {
          read: index + 1,
          season: week.season,
          counted: shown.score.counted,
          captain: shown.score.captain,
          tripleCaptain: member.active_chip === "3xc",
          players,
        }).filter(shownOnBoard),
      );
      // The week's automatic substitutions come after its goals and assists, one board each.
      for (const [out, incoming] of shown.score.autosubs) {
        steps.push([
          {
            key: `sub:replay:${out}:${incoming}`,
            kind: "substitution",
            size: "big",
            out: nameOf(out),
            in: nameOf(incoming),
          },
        ]);
      }
      const shownSteps = steps.filter((items) => items.length > 0);
      shownSteps.forEach((items, index) => {
        timers.push(
          setTimeout(
            () => setBatch({ id: index + 1, items }),
            REPLAY_START_MS + index * REPLAY_STEP_MS,
          ),
        );
      });
      // The last moment's step over, the replay hands the board nothing more.
      timers.push(
        setTimeout(() => setBatch(null), REPLAY_START_MS + shownSteps.length * REPLAY_STEP_MS),
      );
    };
    play().catch(() => undefined);
    return () => {
      read.abort();
      timers.forEach(clearTimeout);
      setBatch(null);
    };
  }, [running, entryId, gameweek, capture, fixtures, forwarder, loadTable, tree]);

  return enabled ? batch : null;
}
