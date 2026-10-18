# Member page boundaries

The member page separates publication reads, advice state and presentation without changing
the public route or component contracts.

| Module | Responsibility |
| --- | --- |
| `pages/LeagueGate.tsx` | The first of the two steps in front of every league page: the league number in the address, found in the published directory, then `MemberGate` inside the league's provider. An address without a number is rewritten to the current league (the claim's, else the one chosen) or shows the entry form in place. In visitor mode (`source="visitor"`, the system's own pages `/gw`, `/moves` and `/rivals`) the league is the visitor's current one rather than the address's, and a league connected there keeps the address and asks the second step in place. |
| `pages/MemberGate.tsx` | The second step: "Sen kimsin?". Until the visitor has said who they are in this league, the page asked for is not drawn and `MemberPicker` stands in its place at the same address. It reads the member list through the shared `useLeagueMembers` read and hands the human rows to `useLeagueIdentity` as the roster. After Onayla it opens the page asked for, or the visitor's own page when the navigation carried `FIND_YOURSELF`, and asks the shell to focus the page. |
| `pages/MemberPicker.tsx` | The picker as a view: the league's human members by name only (manager and team, sorted by name, never in the standings' order), one radio each, and Onayla under them, enabled only for a row of this list. It holds no identity policy. A later sign-in takes its place. |
| `identity/useLeagueIdentity.ts` | The one identity interface the gates, the shell and the pages read: the current league (the address's, else the claim's, else the chosen one), the member claimed in it, its status, `chooseLeague`, `claimMember` and `change`. With the roster it reconciles the claim: a member the list does not hold is dropped, changed names are written back. A sign-in replaces `memberClaim.ts` and this reconciliation; the callers keep the interface. It is a step in the flow, not access control: the published files stay public. |
| `identity/memberClaim.ts` | The claim for this browser tab: one `{leagueId, entryId, managerName, teamName, leagueName}` in sessionStorage (`squadopt.member`), so a reload in the same tab keeps it and a new visit asks again; module memory when storage is refused. Private to the identity module, as is `identity/useChosenLeague.ts` (the league number, in localStorage); `architecture.test.ts` holds both. |
| `pages/LeagueMemberPage.tsx` | Route and loading/error states. The system team's old address (`members/squadopt`) reads as an invalid entry. Re-exports `LeagueMemberView` and `AdviceIssue` for existing callers. |
| `pages/useLeagueMemberData.ts` | Composes the member page's reads: the own squad, the member list, the advice index, the compute service's capabilities, the advice, the window control, the rival, and, where the publish wrote the member's device inputs, the other members' squads the device's statement is made from, with whether they are still being read and which could not be read. It keys the index, capabilities, advice and window-control reads, decides when each read is enabled, and applies the central `CAPABILITIES_READ` policy to capabilities. The own squad, member list, rival and device-rival reads come from the shared hooks in `queries.ts`. |
| `pages/LeagueMemberView.tsx` | Page composition: the notices, the decision section, the squad section, the honesty lines and their disclosure, the plan's detail sections, and the closed tool sections (the held squad first). It places the one fixture rail: a column of its own from 1180 px (and without a shell), beside the squad on a tablet, and a sheet over the page, rendered outside `main`, on a phone. Who the visitor is lives in the shell's sidebar, not on the page. The published context key still remounts the content when its league/member/season/week/capture changes. |
| `pages/MemberTopBar.tsx` | The top bar (the team as the one `h1`, the week, the deadline from the fixture calendar, the score bug). |
| `pages/memberSelection.ts` | The one resolver both `useLeagueMemberData.ts` and `useMemberAdviceView.ts` select through: the device's statement from the member's squad, the members and the device-rival squads, beside the published index and the service's capabilities, and the request the device is asked for. The same inputs give the same rival in both, so the rival the page reads is the rival the device solves against. |
| `pages/useMemberAdviceView.ts` | Existing selection resolution, advice client/job lifecycle, reset effect, checked publication and shown-result choice. |
| `pages/MemberAdviceCard.tsx` | Advice availability, the proof stamp, the substitution boards, the gain strip and captain line, costs, rival comparison, the proposed lineup as a list (the squad section's list view), multiweek sections and the sentences for the "how was this worked out" disclosure. |
| `pages/squadOnPitch.ts`, `pages/MemberSquad.tsx` | Which eleven the pitch draws (the plan's after its transfers, else the squad held), the squad section (`#kadro`: the pitch, the bench, the Saha / Liste toggle) and the held squad as a compact list. |
| `components/MemberPitch.tsx` | The marked pitch (across from 640 px of width, upright below, by container query) and the bench under it. |
| `components/MemberFixtureRail.tsx` | The transfers' and the eleven's next three gameweeks and who meets whom, joined to the fixture calendar by club; the phone sheet registers with the shell. |
| `pages/memberPageTypes.ts` | Types shared by those modules; no runtime dependencies. |
| `data.ts` | Static paths, fetch/deadline handling, response decoding, fixture policy and public loaders. |
| `queries.ts` | `leagueKeys` (`directory`, `members`, `scoreboard`, `entrySquad`, `adviceIndex`), the one spelling of the league cache keys more than one page reads; the hooks `useLeagueMembers`, `useLeagueScoreboard`, `useEntrySquad` (no read while there is no entry id) and `useEntrySquads` (several entries' squads under the same keys, with whether any is still being read and which reads failed); and the central read policies. `LEAGUE_READ` disables retries and keeps a successful read fresh for one minute. `CAPABILITIES_READ` derives those values and enables focus refresh when stale, without polling or computing advice. Every league `useQuery`, and every read a `useQueries` maps, spreads one of these two policies. `queries.test.tsx` fails when another league module spells a shared key or sets its own `retry` or `staleTime`, and when a module's count of `useQuery(` and `useQueries(` calls differs from its central-policy spreads. `/league` (`pages/LeaguePage.tsx`) reads the site index, the ledger and `league.json` through `data/queries.ts`, with the client default of one retry, and stays outside that rule. |
| `publicationShape.ts` | Pure envelope/member/squad/index shape checks. |
| `dataErrors.ts` | The same error classes, re-exported from `data.ts` for compatibility. |

The page modules share their CSS modules and translations. Pure render sections consume
the same checked inputs; they do not start requests. Direction D's top bar, boards and
fixture rail read the fixture calendar the route already reads for the deadline (`fixtures`,
the same query), so the page reads no new document.

The index remains the authority for which advice reads are enabled. Request keys still
include selection and publication context, stale retained index errors still close the gate,
and `checkedAdvice` still rejects malformed or mismatched results. Request abort/deadline
handling remains in the existing request/client/job boundaries. The extraction does not add
a fallback fetch or change error classification.

Runtime validators import only the shared errors and types, never the loader that invokes
them. Shared page types use type-only imports. This keeps validation and type definitions
from introducing a runtime cycle back to routing, requests or views.

Existing tests retain their `LeagueMemberPage` / `LeagueMemberView` and data-error imports.
The member, identity, index, advice, request, error, cost, lineup and window suites exercise
those compatibility paths. Rendering and state/validator statements are also compared with
their pre-extraction source; full production build and browser gates remain separate checks.
