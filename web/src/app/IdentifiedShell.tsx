import { useCallback, useMemo, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";

import { PageShell } from "../design/components/PageShell";
import type { ShellIdentity } from "../design/shell/nav";
import { useLeagueIdentity } from "../features/league/identity/useLeagueIdentity";
import { useLanguage } from "../i18n/context";
import { FIND_YOURSELF, leagueIdInAddress, membersAddress } from "../lib/leagueAddresses";

/**
 * The app shell with the visitor's identity handed in. The shell lives in design/, which
 * reads nothing of the league feature, so the league and the claimed member reach it here
 * as plain props: the sidebar's links, the identity block and its Değiştir.
 */
export function IdentifiedShell({ children }: { children: ReactNode }) {
  const { messages } = useLanguage();
  const location = useLocation();
  const navigate = useNavigate();
  const { leagueId, member, change } = useLeagueIdentity(leagueIdInAddress(location.pathname));

  const identity = useMemo<ShellIdentity>(
    () => ({
      leagueId,
      member:
        member === null
          ? null
          : {
              entryId: member.entryId,
              league: member.leagueName ?? messages.leagueMembers.leagueNumber(member.leagueId),
              name: member.managerName ?? member.teamName ?? messages.leagueMembers.unknownMember,
              team: member.managerName !== null ? member.teamName : null,
            },
    }),
    [leagueId, member, messages],
  );

  // Değiştir drops the claim and asks again in the same league; the next pick opens that
  // member's own page.
  const onChangeMember = useCallback(() => {
    if (leagueId === null) return;
    change();
    navigate(membersAddress(leagueId), { state: FIND_YOURSELF });
  }, [leagueId, change, navigate]);

  return (
    <PageShell identity={identity} onChangeMember={onChangeMember}>
      {children}
    </PageShell>
  );
}
