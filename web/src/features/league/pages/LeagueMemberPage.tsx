import { Link, useParams, useSearchParams } from "react-router";

import { Badge } from "../../../design/components/Badge";
import { Card } from "../../../design/components/Card";
import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { SquadPage } from "../../squad/pages/SquadPage";
import { LeagueDataMissing } from "../data";
import { LeagueMemberView } from "./LeagueMemberView";
import type { AdviceIssue } from "./memberPageTypes";
import { useLeagueMemberData } from "./useLeagueMemberData";
import styles from "./LeagueMemberPage.module.css";

export { LeagueMemberView };
export type { AdviceIssue } from "./memberPageTypes";

export function LeagueMemberPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  const entryParam = useParams().entryId;
  const [searchParams] = useSearchParams();
  const {
    validEntryId,
    squad,
    membersQuery,
    indexQuery,
    members,
    index,
    selection,
    adviceEnabled,
    advice,
    rival,
  } = useLeagueMemberData(entryParam, searchParams);

  if (entryParam === "squadopt") return <SystemLeagueMemberPage />;
  if (!validEntryId) return <EmptyState title={copy.invalidEntry} />;
  if (squad.isPending) return <EmptyState title={copy.loadingEntry} />;
  if (squad.isError) {
    const missing = squad.error instanceof LeagueDataMissing;
    const reasons = missing ? [...new Set(index?.unavailable.map((item) => item.reason))] : [];
    return (
      <EmptyState title={missing ? copy.entryNotAvailable : copy.entryUnreadable}>
        <p>{missing ? copy.entryNotAvailableBody : copy.entryUnreadableBody}</p>
        {reasons.filter(Boolean).map((reason) => (
          <p key={reason}>{reason}</p>
        ))}
        <Link to="/league/members">{copy.backToMembers}</Link>{" "}
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
      rivalSquad={rival.data ?? null}
      adviceIssue={adviceIssue}
      adviceLoading={indexQuery.isPending || (adviceEnabled && advice.isPending)}
      membersIssue={
        membersQuery.isError
          ? membersQuery.error instanceof LeagueDataMissing
            ? "missing"
            : "unavailable"
          : undefined
      }
      onRetryAdvice={() => void advice.refetch()}
      onRetryIndex={() => void indexQuery.refetch()}
      members={members}
      index={index}
    />
  );
}

function SystemLeagueMemberPage() {
  const { messages } = useLanguage();
  const copy = messages.leagueMembers;
  return (
    <div className={styles.systemPage}>
      <Link className={styles.back} to="/league/members">
        {copy.backToMembers}
      </Link>
      <Card
        title={copy.systemTeamTitle}
        aside={
          <Badge tone="accent">
            <span aria-hidden="true">◈</span> {copy.systemTeamBadge}
          </Badge>
        }
      >
        <p className={styles.honesty}>{copy.independentAdviceRule}</p>
      </Card>
      <SquadPage />
    </div>
  );
}
