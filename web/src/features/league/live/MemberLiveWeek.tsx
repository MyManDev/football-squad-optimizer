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
export function MemberLiveWeekView({ squad, live }: { squad: EntrySquad; live: MemberLive }) {
  const { shown, refreshing, refresh } = live;
  if (shown === null) return null;
  return (
    <MemberLiveScoreCard
      key={`${squad.entry.entry_id}:${squad.season}:${shown.gameweek}`}
      entryId={squad.entry.entry_id}
      gameweek={shown.gameweek}
      score={shown.score}
      forecast={shown.forecast}
      names={shown.names}
      onRefresh={refresh}
      refreshing={refreshing}
      activity={shown.activity}
    />
  );
}
