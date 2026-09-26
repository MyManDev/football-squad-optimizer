# Member page boundaries

The member page separates publication reads, advice state and presentation without changing
the public route or component contracts.

| Module | Responsibility |
| --- | --- |
| `pages/LeagueMemberPage.tsx` | Route, loading/error states and the preserved direct system page. Re-exports `LeagueMemberView` and `AdviceIssue` for existing callers. |
| `pages/useLeagueMemberData.ts` | Composes the member page's reads: the own squad, the member list, the advice index, the compute service's capabilities, the advice, the window control and the rival. It keys the index, capabilities, advice and window-control reads, decides when each read is enabled, and sets the capabilities read's `refetchOnWindowFocus: false`. The own squad, member list and rival reads come from the shared hooks in `queries.ts`. |
| `pages/LeagueMemberView.tsx` | Page composition: the notices, the decision section, the squad section, the honesty lines and their disclosure, the plan's detail sections, and the closed tool sections (the held squad first). It renders the plan controls with Hesapla and the WHO block into the shell's sidebar slots through `ShellPortal` (inline when there is no shell), and places the one fixture rail: a column of its own from 1180 px (and without a shell), beside the squad on a tablet, and a sheet over the page, rendered outside `main`, on a phone. The published context key still remounts the content, the slots' parts included, when its league/member/season/week/capture changes. |
| `pages/MemberTopBar.tsx` | The top bar (the team as the one `h1`, the week, the deadline from the fixture calendar, the score bug) and the sidebar's WHO block. |
| `pages/useMemberAdviceView.ts` | Existing selection resolution, advice client/job lifecycle, reset effect, checked publication and shown-result choice. |
| `pages/MemberAdviceCard.tsx` | Advice availability, the proof stamp, the substitution boards, the gain strip and captain line, costs, rival comparison, the proposed lineup as a list (the squad section's list view), multiweek sections and the sentences for the "how was this worked out" disclosure. |
| `pages/squadOnPitch.ts`, `pages/MemberSquad.tsx` | Which eleven the pitch draws (the plan's after its transfers, else the squad held), the squad section (`#kadro`: the pitch, the bench, the Saha / Liste toggle) and the held squad as a compact list. |
| `components/MemberPitch.tsx` | The marked pitch (across from 640 px of width, upright below, by container query) and the bench under it. |
| `components/MemberFixtureRail.tsx` | The transfers' and the eleven's next three gameweeks and who meets whom, joined to the fixture calendar by club; the phone sheet registers with the shell. |
| `pages/memberPageTypes.ts` | Types shared by those modules; no runtime dependencies. |
| `data.ts` | Static paths, fetch/deadline handling, response decoding, fixture policy and public loaders. |
| `queries.ts` | `leagueKeys` (`members`, `scoreboard`, `entrySquad`), the one spelling of the league cache keys more than one page reads; the hooks `useLeagueMembers`, `useLeagueScoreboard` and `useEntrySquad` (no read while there is no entry id); and `LEAGUE_READ`, the one retry and stale-time setting that every `useQuery` call in the league feature spreads. `queries.test.tsx` fails when another league module spells a shared key or sets its own `retry` or `staleTime`, and when a league module's count of `useQuery(` calls differs from its count of `...LEAGUE_READ` spreads. `/league` (`pages/LeaguePage.tsx`) reads the site index, the ledger and `league.json` through `data/queries.ts`, with the client default of one retry, and stays outside that rule. |
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
