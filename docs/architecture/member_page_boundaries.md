# Member page boundaries

The member page separates publication reads, advice state and presentation without changing
the public route or component contracts.

| Module | Responsibility |
| --- | --- |
| `pages/LeagueMemberPage.tsx` | Route, loading/error states and the preserved direct system page. Re-exports `LeagueMemberView` and `AdviceIssue` for existing callers. |
| `pages/useLeagueMemberData.ts` | Existing member/index/advice/rival React Query reads, keys, enablement, stale times and retry choices. |
| `pages/LeagueMemberView.tsx` | Page composition: the notices, the decision section, the honesty lines and their disclosure, the closed tool sections and the held squad. It renders the plan controls with Hesapla and the WHO block into the shell's sidebar slots through `ShellPortal` (inline when there is no shell). The published context key still remounts the content, the slots' parts included, when its league/member/season/week/capture changes. |
| `pages/MemberTopBar.tsx` | The top bar (the team as the one `h1`, the week, the deadline from the fixture calendar, the score bug) and the sidebar's WHO block. |
| `pages/useMemberAdviceView.ts` | Existing selection resolution, advice client/job lifecycle, reset effect, checked publication and shown-result choice. |
| `pages/MemberAdviceCard.tsx` | Advice availability, the proof stamp, the substitution boards, the gain strip and captain line, costs, rival comparison, proposed lineup, multiweek sections and the sentences for the "how was this worked out" disclosure. |
| `pages/memberPageTypes.ts` | Types shared by those modules; no runtime dependencies. |
| `data.ts` | Static paths, fetch/deadline handling, response decoding, fixture policy and public loaders. |
| `publicationShape.ts` | Pure envelope/member/squad/index shape checks. |
| `dataErrors.ts` | The same error classes, re-exported from `data.ts` for compatibility. |

The page modules share their CSS modules and translations. Pure render sections consume
the same checked inputs; they do not start requests. Direction D's top bar and boards read
the fixture calendar the route already reads for the deadline (`fixtures`, the same query),
so the page reads no new document.

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
