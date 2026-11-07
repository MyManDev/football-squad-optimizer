import { isMemberTool, membersAddress } from "../../../lib/leagueAddresses";
import { useLeagueId } from "../useLeague";
import { Link, useParams, useSearchParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { useFixtures } from "../../fixtures/data";
import { LeagueDataMissing } from "../data";
import { gameweekDeadline, passedDeadline, useMinuteClock } from "../advice/deadline";
import { useLeagueScoreboard, useSuggestionHistory } from "../queries";
import { lastWeekResult } from "./lastWeekResult";
import { LeagueMemberView } from "./LeagueMemberView";
import { MemberPageSkeleton } from "./MemberPageSkeleton";
import type { AdviceIssue } from "./memberPageTypes";
import { useLeagueMemberData } from "./useLeagueMemberData";

export { LeagueMemberView };
export type { AdviceIssue } from "./memberPageTypes";

export function LeagueMemberPage() {
  const { messages } = useLanguage();
  const leagueId = useLeagueId();
  const copy = messages.leagueMembers;
  const params = useParams();
  const entryParam = params.entryId;
  const toolParam = params.tool;
  const tool = isMemberTool(toolParam) ? toolParam : undefined;
  const [searchParams] = useSearchParams();
  const {
    validEntryId,
    squad,
    indexQuery,
    members,
    index,
    selection,
    adviceEnabled,
    advice,
    coachNews,
    rival,
    duel,
    duelId,
    deviceRivals,
    windowControl,
    client,
    capabilities,
    computeService,
    computePending,
  } = useLeagueMemberData(entryParam, searchParams);
  // The published calendar: the deadline, and the clubs' next gameweeks on the boards.
  const fixtures = useFixtures();
  // One clock for the page: the deadline check and the top bar's countdown read it.
  const now = useMinuteClock();
  const deadlinePassed = passedDeadline(
    gameweekDeadline(fixtures.data, squad.data?.payload.season, squad.data?.payload.gameweek),
    now,
  );
  // The card of the member's latest finished week reads the league's scoreboard, under the
  // key /league reads it by, and only once that holds a finished week for this member, the
  // member's history, under the key their history page reads it by. Neither holds the page
  // back: missing or unreadable, the card or its line is left out.
  const ownSquad = squad.data?.payload;
  const scoreboard = useLeagueScoreboard(ownSquad !== undefined);
  const scoreboardView = scoreboard.isError ? null : (scoreboard.data?.payload ?? null);
  const history = useSuggestionHistory(
    ownSquad?.entry.entry_id ?? 0,
    ownSquad !== undefined && lastWeekResult(ownSquad, scoreboardView, null) !== null,
  );

  if (toolParam !== undefined && tool === undefined) {
    return <EmptyState page title={messages.shell.notFound} />;
  }
  if (!validEntryId) return <EmptyState page title={copy.invalidEntry} />;
  // The squad is the page's first read and its longest wait on a cold visit: the page's
  // shape stands in for it, its words read to a screen reader only.
  if (squad.isPending) return <MemberPageSkeleton />;
  if (squad.isError) {
    const missing = squad.error instanceof LeagueDataMissing;
    return (
      <EmptyState page title={missing ? copy.entryNotAvailable : copy.entryUnreadable}>
        {missing ? <p>{copy.entryNotAvailableBody}</p> : null}
        <Link to={leagueId > 0 ? membersAddress(leagueId) : "/"}>{copy.backToMembers}</Link>{" "}
        {!missing ? (
          <button type="button" onClick={() => void squad.refetch()}>
            {copy.retryPublishedRead}
          </button>
        ) : null}
      </EmptyState>
    );
  }
  // Published advice that is missing or unloadable does not close the page: the member
  // context is valid, so the squad and the compute control stay, and the advice card says
  // what is missing. Only this pair is solved per member, so an unpublished combination
  // is a normal outcome rather than a fault the reader should report.
  const adviceIssue: AdviceIssue | undefined = indexQuery.isError
    ? indexQuery.error instanceof LeagueDataMissing
      ? "index-missing"
      : "index-error"
    : selection.status !== "ready"
      ? selection.status
      : advice.isError
        ? advice.error instanceof LeagueDataMissing
          ? "published-missing"
          : "unavailable"
        : undefined;
  return (
    <LeagueMemberView
      squad={squad.data}
      advice={adviceEnabled && !advice.isError ? (advice.data ?? null) : null}
      coachNews={coachNews.isError ? null : (coachNews.data ?? null)}
      rivalSquad={rival.data ?? null}
      duelSquad={duelId !== null && !duel.isError ? (duel.data ?? null) : null}
      duelIssue={
        duelId === null
          ? undefined
          : duel.isError
            ? "unreadable"
            : duel.isPending
              ? "loading"
              : undefined
      }
      deviceRivals={deviceRivals}
      windowControl={windowControl.isError ? null : (windowControl.data ?? null)}
      adviceIssue={adviceIssue}
      adviceLoading={indexQuery.isPending || (adviceEnabled && advice.isPending)}
      onRetryAdvice={() => void advice.refetch()}
      onRetryIndex={() => void indexQuery.refetch()}
      members={members}
      index={index}
      client={client}
      capabilities={capabilities}
      computeService={computeService}
      computePending={computePending}
      deadlinePassed={deadlinePassed}
      now={now}
      fixtures={fixtures.data ?? null}
      fixturesPending={fixtures.isPending}
      scoreboard={scoreboardView}
      history={history.isError ? null : (history.data ?? null)}
      tool={tool}
    />
  );
}
