import type { FixturesPayload } from "../../fixtures/types";
import { MemberLiveScoreCard } from "../../liveScore/MemberLiveScoreCard";
import type { EntrySquad } from "../types";
import { useMemberLiveScore, type MemberLiveDependencies } from "./useMemberLiveScore";

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
  const { shown, refreshing, refresh } = useMemberLiveScore(squad, fixtures, dependencies);
  if (shown === null) return null;
  return (
    <MemberLiveScoreCard
      gameweek={shown.gameweek}
      score={shown.score}
      names={shown.names}
      onRefresh={refresh}
      refreshing={refreshing}
    />
  );
}
