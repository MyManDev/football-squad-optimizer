import { useState } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import { MemberLiveScoreCard } from "../../liveScore/MemberLiveScoreCard";
import type { EntrySquad } from "../types";
import {
  useMemberLiveScore,
  type MemberLive,
  type MemberLiveDependencies,
} from "./useMemberLiveScore";

/**
 * The member's live week on their page (#1008): the card of #1204, with its refresh, once a
 * week is read and scored. Nothing at all while it is read or when there is none.
 */
export function MemberLiveWeek({
  squad,
  fixtures,
  dependencies,
}: {
  squad: EntrySquad;
  fixtures: FixturesPayload;
  dependencies?: MemberLiveDependencies;
}) {
  const live = useMemberLiveScore(squad, fixtures, dependencies);
  return <MemberLiveWeekView squad={squad} live={live} />;
}

/** The card and pitch can share one read and one refresh. */
export function MemberLiveWeekView({
  squad,
  live,
  held = 0,
  waiting = false,
}: {
  squad: EntrySquad;
  live: MemberLive;
  /** Points the GOL board has still to bring to the score. */
  held?: number;
  /** Whether the GOL board has a moment still to land. */
  waiting?: boolean;
}) {
  const { shown, refreshing, refresh } = live;
  // While the board brings a read's moments, the card's lists (the players, the captain, the
  // substitutions) stay as the read before left them, so nothing moves under the board; they
  // take the new read once its points have landed.
  const [settled, setSettled] = useState(shown);
  if (!waiting && shown !== settled) setSettled(shown);
  if (shown === null) return null;
  const lists =
    waiting && settled !== null && settled !== shown && settled.gameweek === shown.gameweek
      ? { score: settled.score, activity: settled.activity }
      : undefined;
  return (
    <MemberLiveScoreCard
      key={`${squad.entry.entry_id}:${squad.season}:${shown.gameweek}`}
      entryId={squad.entry.entry_id}
      held={held}
      gameweek={shown.gameweek}
      score={shown.score}
      lists={lists}
      forecast={shown.forecast}
      names={shown.names}
      onRefresh={refresh}
      refreshing={refreshing}
      activity={shown.activity}
    />
  );
}
