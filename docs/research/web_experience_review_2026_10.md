# Member web experience: practice review, October 2026

Research review for the [15 October assignment](https://github.com/MyManDev/football-squad-optimizer/issues/1012#issuecomment-6193076703). This record gives the owner ranked interface choices. It contains no implementation, runner, preregistration, measurement, usability experiment or new outcome reading. The migration, weekly run, admin page and architecture programme remain outside the assignment.

## Recommendation and reading basis

Start with **a clearer comparison of two existing plans**, then **a short, grounded explanation attached to a transfer or captain**, followed by **a longer fixture lens inside the existing rail**. These could make the existing decision loop easier to inspect without requiring a new forecast source. Accessibility is a condition of every choice. Installation, offline work, a chip forecast card and member live scores belong to existing owner-selected programmes, not duplicate implementations proposed here.

The repository baseline is `develop` commit `792bef77f9583c8a4a88d8445d246ed341f30814`. References describe source and contracts at that revision; no production browser, real member session or private source was exercised. External product pages and primary design sources were read on 15 October 2026. Product pages establish advertised interaction patterns, not evidence that those patterns improve FPL results.

Read first: the whole product roadmap; the device-plan contract including its v2 table and refusal rules; the member page composition, advice, comparison, preferences, chip rule and fixtures; and the direction D implementation record. The roadmap's current-position section is explicitly dated September and describes a particular publication (`docs/product/roadmap.md:8-24`). It is background, not a substitute for October source.

**Redesign reference.** The brief names a 24 September redesign record. No separately dated tracked document was located. The roadmap identifies direction D and PR #798 (`docs/product/roadmap.md:20-24`); [that implementation record](https://github.com/MyManDev/football-squad-optimizer/pull/798) was opened on 25 September and describes the owner's approved canvas. It specifies the light green surface, left navigation, substitution boards, pitch/list switch, responsive fixtures and mobile drawer. This review uses that record and the current components, without claiming to have read a missing canvas or inventing its date.

## What already exists, and what the data can support

| Surface | Observed repository basis |
| --- | --- |
| Primary decision and settings | The page composes a decision, lineup, fixture rail, settings, comparison tools and resource cards. Controls now sit below the decision, with a link and a polite compute-status line; do not assume the original sidebar placement still holds (`web/src/features/league/pages/LeagueMemberView.tsx:281-370`, `web/src/features/league/pages/LeagueMemberView.tsx:410-467`, `web/src/features/league/pages/LeagueMemberView.tsx:520-555`). |
| Human comparison | A board already pins at most three completed, context-matched plans and a personal preference/note. Storage is per tab, bound to the entire squad publication; changed context empties it (`web/src/features/league/advice/DecisionWorkbench.tsx:35-99`, `web/src/features/league/advice/decisionBoard.ts:21-58`, `web/src/features/league/advice/decisionBoard.ts:100-137`). |
| What-if constraints | Keep/avoid, no-hit and save-chip preferences already have their own panel. Its player catalogue is read from the service; this is not an existing offline device capability (`web/src/features/league/advice/DecisionPreferencesPanel.tsx:23-103`; `docs/decision_preferences.md:1-30`). |
| Device answer | The one-week current-model path supports plain points, a held chip, a named rival or an offered Top100 weight. Preferences, football and longer windows stay outside this selector. Captures and digests bind the inputs; a browser cache alone is not a complete offline app (`docs/contracts/league_device_plan_v1.md:93-150`, `docs/contracts/league_device_plan_v1.md:152-202`; `web/src/features/league/device/selection.ts:53-85`). |
| Available explanation fields | Transfers have a reason code and cumulative share of the gain against holding. Hit charge belongs to the week. Football role rows may carry fixture minutes and point components; those are optional, not a universal explanation for every current-model player (`web/src/features/league/types/index.ts:193-212`, `web/src/features/league/types/index.ts:448-506`). |
| Existing component explanation | RoleForecast already renders expected minutes and optional point components. ExpectedLineup already exposes starting, autosub, captain/vice and chip contributions. A new generic breakdown page would duplicate these (`web/src/features/league/advice/RoleForecast.tsx:61-105`, `web/src/features/league/advice/ExpectedLineup.tsx:33-70`). |
| Rival context | Shared, recommended-only and rival-only player sets already derive from matched advice/squad captures. The contract also carries overlap, captain agreement and a point gap (`web/src/features/league/advice/rivalPlayers.ts:3-55`, `web/src/features/league/types/index.ts:543-550`). |
| Fixtures | The existing rail shows transfers, the eleven's next three weeks and players meeting each other. It distinguishes blank, absent and double weeks, encodes home/away, and deliberately has no difficulty rating (`web/src/features/league/components/MemberFixtureRail.tsx:38-101`, `web/src/features/league/components/MemberFixtureRail.tsx:145-147`). |
| Chips | Held/used chip resources and forced chip plans are distinct from an automatic timing recommendation (`web/src/features/league/components/ViewerChips.tsx:14-61`, `docs/contracts/league_device_plan_v1.md:157-163`). The optional forecast is typed unknown and **no member page reads it**; the pure device rule exists without display copy (`web/src/features/league/types/PROVISIONAL_CONTRACT.md:69-93`, `web/src/features/league/device/chipForecast/rule.ts:1-55`). |
| History and match scores | Member history already aggregates comparable scored weeks. The older system provisional score is a separate named-eleven basis, without autosubs/vice recovery, and has no polling service (`web/src/features/league/history/historySummary.ts:3-31`, `docs/live_score_view.md:35-49`). It is not a ready-made official member live total. |

## Practice sources and what to borrow

| Source | Observed principle and relevance |
| --- | --- |
| P1, Microsoft HAX / Amershi et al. | Local explanations and what-if views should help inspect an output and correct inputs. HAX also cautions that an explanation can increase trust without increasing correctness. Borrow inspectable evidence and user control; do not write a persuasive story unsupported by a solve. [Guideline 11](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-why-the-system-did-what-it-did/), [CHI 2019 paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf). |
| P2, FPL Review's own solver guide | The guide describes multiple distinct solution lines, include/exclude scenarios and separate planning/evaluation settings. Borrow a small menu of named alternatives. Its tuning defaults and language about risk are not evidence for changing this repository's policy. [Solver Settings, Solve Lines and Solve Speed](https://docs.fplreview.com/the-model/solvers/settings/). |
| P3, FPL Team's own product pages | The site advertises future transfer paths, live league movement and a fixture rotation planner. Borrow a visible path through weeks and a focused comparison task; do not import claims of better rank or a refresh cadence. [Product page](https://fpl.team/), [rotation planner](https://fpl.team/rotation-planner/). |
| P4, SoccerStories | Perin, Vuillemot and Fekete connect phase overviews to detailed football views. Two qualitative studies with analysts motivate linked context, not a proven benefit for casual fantasy managers. Borrow linked selection between a player and their fixtures; event maps would require a different source. [Author deposit, TVCG 2013](https://openaccess.city.ac.uk/id/eprint/16701/). |
| P5, W3C | WCAG 2.2 gives concrete requirements for keyboard use, relationships, color, reflow, focus and status updates. Apply them to the decision task, rather than adding a separate accessibility mode. [WCAG 2.2](https://www.w3.org/TR/WCAG22/). |
| P6, web.dev | Installation and offline caching are separate mechanisms. Caching needs an explicit asset/data strategy; install behavior varies across browsers. Borrow an intentional saved-plan flow and platform-appropriate install affordances, not an unconditional install banner. [Caching](https://web.dev/learn/pwa/caching/), [installation](https://web.dev/learn/pwa/installation/). |
| P7, RFC 5545 | iCalendar defines events, stable identifiers, UTC date-times and alarms. It supports exporting deadline facts; it does not make a downloaded file a subscribed, continuously updated calendar. [RFC 5545, sections 3.6.1, 3.6.6 and 3.8](https://www.rfc-editor.org/rfc/rfc5545). |

No conversion, retention, point-gain or task-time uplift is claimed from these sources. The ranking below is a product judgment based on available inputs, task usefulness and implementation scope.

## Ranked ideas

Effort is an initial estimate in engineer-days for one engineer familiar with this application, including TR/EN copy, focused tests and browser checks. It excludes owner design decisions, review wait, source acquisition and operational changes. These are estimates, not measurements or commitments. An implementation choice remains a separate assignment.

| Priority | Idea | Increment over current page | Estimate | Status |
| --- | --- | --- | --- | --- |
| 1 | A/B differences in the existing decision board | Show what changed, with a common scoring basis | 3-5 days | Best first new extension |
| 2 | Grounded transfer and captain explanation | Put existing reasons/evidence next to the affected choice | 2-4 days; a new counterfactual solve adds 5-8 | Separate display from new computation |
| 3 | Fixture lens for the selected plan length | Link the selected move/player to a 1/3/5-week schedule | 2-4 days | Existing calendar, no new rating |
| 4 | Task accessibility and mobile refinement | Make the new comparisons usable by keyboard, touch and screen reader | 2-4 days across priorities 1-3 | Required within each chosen feature |
| 5 | Rival lens on the same comparison | Highlight the exact shared/different sets and captain | 2-3 days | Extend existing set view |
| 6 | Deadline calendar export | Export the published deadline and plan link | 1-2 days standalone | Coordinate with #1011 |
| 7 | Saved plan and home-screen installation | A coherent read-only offline bundle and explicit saved context | 8-12 days combined | Existing #1011 decision scope |
| 8 | Decision note revisited with history | Let the member revisit their own recorded reason | 4-7 days | Requires persistence/privacy choice |
| 9 | Member live-match lens | Current member score, match progress and factual event changes | 3-5 days UI after a source/score contract exists; 8-15 more for that contract/integration | Existing #1008 lane |
| 10 | Chip timing card | A supported play/hold result beside the held-chip facts | 2-4 days display after accepted inputs; 4-7 more for device integration | Existing #1003 lane |

### 1. Compare the changes between two pinned plans

**Source and member view.** P1's what-if pattern and P2's distinct solution lines support an A/B comparison: transfers, captain, lineup, hits, bank and free transfers in aligned rows. On a phone, select one comparison pair and show its differences vertically. Keep up to three stored cards, but compare only two at a time. This extends the existing three-plan board instead of proposing a replacement (`web/src/features/league/advice/DecisionWorkbench.tsx:35-99`).

**Data already held.** Each pinned item includes the request and complete advice envelope; the board already computes net/horizon totals and preserves missing values (`web/src/features/league/advice/decisionBoard.ts:7-16`, `web/src/features/league/advice/decisionBoard.ts:61-97`). Existing identity checks bind the member, squad basis and capture (`web/src/features/league/advice/decisionBoard.ts:21-58`).

**New work.** Derive set differences and align weeks client-side. No new publication or solve is needed for two already completed answers. Compare point differences only for matching member, capture, model/fingerprint, horizon and scoring basis. Across models or horizons, show the two labeled columns independently; do not rank their raw totals. The existing model comparison already preserves settings and needs an explicit click (`web/src/features/league/advice/ModelComparison.tsx:11-97`). The separate window comparison intentionally shows two totals without a subtraction, with mismatches hidden by tests; do not silently change that contract (`web/src/features/league/pages/MemberAdviceCard.comparison.test.tsx:47-85`).

**Wording and effort.** Proposed labels: TR "Plan A", "Plan B", "Değişen oyuncular", "Transfer cezası"; EN "Plan A", "Plan B", "Changed players", "Transfer hits". No win-rate badge, confidence meter or best-overall claim. 3-5 days. Value: less mental subtraction and fewer mismatched comparisons; benefit remains unmeasured.

### 2. Explain this transfer and this captain with actual evidence

**Source and member view.** P1 supports opening a short explanation from a move or the armband. First show the published reason, the relevant fixtures, that player's expected points and the whole plan's net gain. Optional component details can use the already rendered football data; they are an extension of placement, not a new explanatory model (`web/src/features/league/advice/RoleForecast.tsx:61-105`).

**Data already held.** Move reason codes, nullable gain shares, weekly hit charge, captain/vice and optional role components are explicit fields (`web/src/features/league/types/index.ts:193-212`, `web/src/features/league/types/index.ts:448-506`). Move figures are shares of a cumulative sequence, not independent marginal values. Their order and nullability are part of the device contract (`docs/contracts/league_device_plan_v1.md:71-80`).

**New work.** The display-only version maps existing codes to short factual labels and joins the calendar by club, without new publication. It must not say that a transfer caused extra clean-sheet points unless that contrast was actually computed. A stronger "keep this player" or "captain this other player" explanation needs a separately solved legal alternative, the same resources and scoring basis, plus fields binding that comparison. Keep/avoid exists, but the device currently refuses preferences and has no arbitrary forced-captain request (`web/src/features/league/advice/DecisionPreferencesPanel.tsx:23-103`, `web/src/features/league/device/selection.ts:53-85`, `web/src/features/league/device/selection.ts:20-24`). Do not emulate a re-solve by subtracting two standalone player projections.

**Wording and effort.** TR "Bu transfer", "Kaptan", "Fikstür", "Beklenen puan", "Bu oyuncuyu tut"; EN "This transfer", "Captain", "Fixtures", "Expected points", "Keep this player". The last action is only a proposal for a supported future control, not an existing device promise. No generated football narrative, percentages or unverified causal language. 2-4 days for existing evidence placement; an explicit counterfactual request/solve/response path adds an estimated 5-8 days and requires a separate choice.

### 3. Extend the fixture rail to the chosen plan length

**Source and member view.** P3's rotation-planning interaction and P4's linked overview/detail suggest selecting a transfer or lineup player to highlight their fixtures across the selected 1/3/5 weeks. Show every opponent and venue in a double, and a factual blank marker. A paired A/B fixture row can sit below the transfer comparison. Preserve the direction D rail/sheet rather than introducing a second competing fixture panel ([redesign](https://github.com/MyManDev/football-squad-optimizer/pull/798)).

**Data already held.** The fixture document includes season, source capture, gameweeks, deadlines, kickoff times, teams and results; the rail already joins it by club (`web/src/features/fixtures/types.ts:3-32`, `web/src/features/league/components/MemberFixtureRail.tsx:89-101`). Its current horizon is explicitly three weeks (`web/src/features/league/components/MemberFixtureRail.tsx:145-147`).

**New work.** Client-side week selection, linked highlighting and list alternatives, with no new rating, source or publication. Preserve the distinction between a listed blank and an unlisted week. Do not use red/green difficulty heatmaps for a calendar that carries no such rating (`web/src/features/league/components/MemberFixtureRail.tsx:38-61`, `web/src/features/league/clubFixtures.ts:1-23`). Rich pass maps from P4 would need event-location data, not this fixture contract, and are not recommended here.

**Wording and effort.** TR "1 hafta", "3 hafta", "5 hafta", "Evinde", "Deplasmanda", "Maç yok"; EN "1 week", "3 weeks", "5 weeks", "Home", "Away", "No match". A missing cell is not labeled "No match". No expected result, chance or invented fixture difficulty. 2-4 days.

### 4. Make the decision task accessible on a phone

**Source and member view.** P5 requires keyboard access, meaningful relationships, visible unobscured focus, reflow and appropriate status announcements. Its target-size criterion has a 24 CSS pixel minimum with spacing and other exceptions; that is a standard, not a claim about current defects ([target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)). Use native table/list semantics for comparison rows, text beside symbols and alternatives to dragging. Announce completion when it changes without continually announcing a timer ([status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)).

**Data already held.** The member page already has a polite result status, preserves DOM reading order across layouts, and uses a modal fixture sheet with focus behavior (`web/src/features/league/pages/LeagueMemberView.tsx:420-467`, `web/src/features/league/components/MemberFixtureRail.tsx:99-101`, `web/src/features/league/components/MemberFixtureRail.tsx:135-177`). These are assets to preserve, not evidence that the entire flow conforms.

**New work.** For selected new views, specify focus on open/close, accessible row/column names, reduced motion, zoom/reflow and touch targets. No new publication, prediction or API is required. Do not add more sticky controls over the comparison or duplicate the compute action. Proposed status copy: TR "Plan hazır", "Plan A seçildi"; EN "Plan ready", "Plan A selected". No probability symbols or percentage progress estimate. Estimate 2-4 days shared across priorities 1-3. No accessibility audit or conformance measurement was run for this record.

### 5. Put rival context next to the exact changes

**Source and member view.** P3 advertises mini-league context; borrow task context, not a live rank claim. Extend the existing shared/different player lists by linking a name to the pitch, transfer row and fixtures. Show captain agreement and the recorded league gap beside the selected rival. Do not add a rival-behavior predictor.

**Data already held.** Matched advice and rival documents support exact set arithmetic and already carry overlap, captain agreement and expected point gap (`web/src/features/league/advice/rivalPlayers.ts:3-55`, `web/src/features/league/types/index.ts:543-550`). The existing set view compares the plan's fifteen with the rival's eleven. Label that grain explicitly; do not call it common starters unless both sets actually contain elevens (`web/src/features/league/advice/rivalPlayers.ts:31-54`).

**New work.** Linked highlights and a deliberate fifteen-versus-eleven or eleven-versus-eleven choice, with client-side set derivation and no new source. A different expected scoring basis needs an explicit new calculation rather than a relabeled count. Missing or mismatched rival data suppresses that comparison, using the current identity guards (`web/src/features/league/advice/rivalPlayers.ts:10-29`).

**Wording and effort.** TR "Ortak oyuncular", "Sende olanlar", "Rakipte olanlar", "Aynı kaptan"; EN "Shared players", "Your players", "Rival players", "Same captain". Specify the squad/eleven in the heading. No safety, differential success rate, ownership percentage or chance of overtaking. Existing crowd-relative window claims failed their declared stop rule, so this is a facts-and-points lens (`docs/measurements_index.md:180-184`). 2-3 days.

### 6. Export deadline facts to a calendar

**Source and member view.** P7 supports a downloadable event for the selected deadline and a link back to the member plan. An alarm time is a member choice, not a promised background notification. A one-time file and a subscribed feed are distinct product choices under [#1011](https://github.com/MyManDev/football-squad-optimizer/issues/1011).

**Data already held.** Published `deadline_utc`, season/gameweek and the plan route suffice. The deadline helper already binds season and leaves an unknown deadline absent (`web/src/features/fixtures/types.ts:19-32`, `web/src/features/league/advice/deadline.ts:16-25`).

**New work.** Client-side iCalendar serialization with a stable event UID, valid UTC date-time, escaping and chosen alarm, plus a bounded plan URL. No new forecast or publication is necessary for a file export. A subscribed feed would add a publication/update contract; it is not included in the 1-2 day estimate. No reminder, automation or calendar item is created by this review.

**Wording.** TR "Son tarihi takvime ekle"; EN "Add deadline to calendar". Event title: "FPL GW7 deadline" / "FPL 7. hafta son tarih" as an illustrative template, using the document's actual week and time in implementation. No invented next deadline or guarantee of notification.

### 7. Save one coherent plan for offline reading, with optional installation

**Source and member view.** P6 distinguishes installing a home-screen app from fetching and retaining usable data. Recommend a member-initiated save, followed by a compact saved-plan screen. Positive factual labels could be TR "Kaydedilen plan", "Kayıt zamanı", "Güncel planı aç"; EN "Saved plan", "Saved at", "Open latest plan". Show the saved week and timestamp, without a paragraph of caveats.

**Data already held.** The board stores completed advice and squad context in session storage. The device table has a capture/digest identity and a worker-based solver, but those alone do not guarantee all required files are cached (`web/src/features/league/advice/decisionBoard.ts:100-137`, `docs/contracts/league_device_plan_v1.md:93-150`, `web/src/features/league/device/useDevicePlan.ts:94-129`). The entry HTML links a favicon, not a web app manifest; the inspected bootstrap registers no service worker (`web/index.html:1-15`, `web/src/main.tsx:1-29`). This supports treating a coherent offline workflow as new work, not claiming that HTTP caching already provides it.

**New work.** Save a versioned bundle of shell/assets, completed advice, squad, required calendar and identity as one accepted unit; add expiry/refresh behavior and a delete action. Offline re-solving additionally needs the exact device table, wasm/worker assets and any rival document. Keep service-only preferences, football and multi-week answers outside an offline solve promise (`docs/contracts/league_device_plan_v1.md:178-202`). Never queue a transfer or automatically replay an old compute request when connectivity returns.

Installation adds a manifest/icons and appropriate browser affordances, but is useful only after the saved-plan path works. Exact browser support and cache policies need review at implementation time. Estimated 8-12 days for saved read-only plan plus installation; full offline solve adds an estimated 4-7. Scope remains [#1011](https://github.com/MyManDev/football-squad-optimizer/issues/1011), awaiting the owner's selection of product behavior. This is not a request to change hosting.

### 8. Revisit a private decision note beside the member's history

**Source and member view.** P1's interaction-memory principle suggests returning to a member's own recorded reason after the week. Pair the chosen plan, note and recorded score basis. Use factual prompts such as TR "Tercihim", "Notum", "Haftanın kaydı"; EN "My choice", "My note", "Week record". Do not claim the member followed the recommendation.

**Data already held.** The current board has a preferred plan and note, but explicitly discards them when squad/publication context changes. History summarizes only weeks where both compared values exist (`web/src/features/league/advice/decisionBoard.ts:100-137`, `web/src/features/league/history/historySummary.ts:3-31`). A durable personal decision journal is therefore a different storage/lifecycle choice.

**New work.** An opt-in local journal would require retaining the complete original basis, data deletion/export, explicit association with a scored record and a distinction between selection and actual FPL execution. A cross-device journal requires authentication/storage work and is excluded from this estimate. No new public publication is necessary for local notes; new retained private state is necessary. 4-7 days after the owner chooses retention. It is lower priority than improving comparisons because it introduces a longer-lived personal-data surface.

### 9. A member live-match view built on an official scoring basis

**Source and member view.** P3 advertises live team/league movement. P4's linked context suggests a compact member XI with score changes and fixture progress, expandable to player contributions. Borrow that task structure. Do not copy effective-ownership, rank-probability or danger-score language.

**Data already held.** The calendar provides fixture state only as captured, and the older provisional score describes the system's named eleven rather than a complete official member score (`web/src/features/fixtures/types.ts:9-17`, `docs/live_score_view.md:28-49`). Its capture timestamp is not a live refresh guarantee. Reusing it unchanged would give the wrong autosub/vice basis.

**New work.** Requires a member score contract with picks, chip/hit treatment, official autosubs/vice logic, per-player final/provisional distinctions, coherent source timestamp and admitted refresh source. The UI can then show TR "Maçlar", "Anlık puan", "Son güncelleme"; EN "Matches", "Live points", "Updated at", only with a source that actually supports the live label. Before that, a captured score should be labeled as a recorded score instead. No caveat paragraph is needed to distinguish these positive factual states.

This is the existing [#1008](https://github.com/MyManDev/football-squad-optimizer/issues/1008) lane. Estimate 3-5 days for UI after accepted scoring/source contracts; 8-15 additional days is an initial contract/integration estimate, excluding provision of a new live feed. A new collector, scheduler or weekly stage is not proposed by this record.

### 10. A chip timing card only through its existing assignment

**Source and member view.** P2's alternative-plan pattern supports pairing "play" and "hold" choices with their named gameweeks and net points, rather than an urgency gauge. P3's fixture planner suggests placing chip dates in the existing schedule context. Proposed labels: TR "Şimdi kullan", "Sakla", "Hedef hafta"; EN "Play now", "Hold", "Target week". A rule recommendation must never become a success-rate or chance claim.

**Data already held.** Held chip windows and one-week chip gain versus no-chip are part of the device-plan contract (`docs/contracts/league_device_plan_v1.md:130-163`). A private optional `chip_forecast` may exist, but its shape is not checked by the page and no card consumes it. The TypeScript rule is arithmetic preparation without display copy (`web/src/features/league/types/PROVISIONAL_CONTRACT.md:69-93`, `web/src/features/league/device/chipForecast/rule.ts:1-55`).

**New work.** A verified input producer, accepted calendar coverage, typed forecast reader, complete request/capture identity and a device integration are prerequisites. Do not cast the unknown field into a card, infer missing gains or reopen the automatic multi-week chip policy as a UI tweak. Automatic selection is explicitly not offered under the recorded planner limitation (`docs/chip_strategy.md:10-23`). This belongs to [#1003](https://github.com/MyManDev/football-squad-optimizer/issues/1003), not a new research implementation. Estimate 2-4 days display after inputs are accepted, plus 4-7 for device integration; no measurement result or release is implied.

## Member wording and decision boundaries

The owner's rule is stricter than some existing legacy text or test exceptions: **every proposed member-facing label above avoids probability, percentage, odds, chance and likelihood wording, and no proposed member copy contains a caveat or limit sentence**. The authority is the [assignment's house rules](https://github.com/MyManDev/football-squad-optimizer/issues/1012#issuecomment-6193076703). Existing probability tests and component copy explain why reusing an old string is not sufficient evidence of compliance (`web/src/features/league/pages/adviceNoProbability.test.tsx:1-8`, `web/src/features/league/advice/RoleForecast.tsx:6-48`).

Use factual labels for week, plan identity, points, hits, source time and available actions. Hide a missing optional comparison rather than manufacture a zero. Describe a new solve as a member action, not as background magic. Notes stay personal and never become forecast training labels. A confidence badge, implied chance meter, forecast price movement, detailed injury probability editor, richer tactical event map, chatbot or automatic execution would add a new product/source/model question; none is recommended as an incidental interface upgrade.

If the owner selects priorities 1-3, the next assignment can be a concrete design and implementation proposal that preserves the current member context and direction D. It should name the exact data fields and any new comparison computation before implementation. Priorities 6-10 should be reconciled with their existing owner decisions instead of opening duplicate tickets. This review makes no change to a product route, publication, shared contract, measurement or roadmap commitment.

## References

- **P1.** Amershi, S. et al. (2019). [Guidelines for Human-AI Interaction](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf), CHI 2019. [Microsoft HAX Guideline 11 and explanation patterns](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-why-the-system-did-what-it-did/). Source for explanation/control principles, not FPL benefit.
- **P2.** FPL Review. [Solver Settings](https://docs.fplreview.com/the-model/solvers/settings/), especially Solve Lines and Solve Speed. First-party description of interaction and solver choices, not independent validation.
- **P3.** FPL Team. [Product page](https://fpl.team/) and [Rotation Planner](https://fpl.team/rotation-planner/). First-party advertised planning, fixture and live-league patterns; no claimed performance uplift is adopted.
- **P4.** Perin, C., Vuillemot, R. and Fekete, J. (2013). [SoccerStories: A Kick-off for Visual Soccer Analysis](https://openaccess.city.ac.uk/id/eprint/16701/). TVCG 19(12), 2506-2515, DOI 10.1109/TVCG.2013.192. Linked context and qualitative analyst studies.
- **P5.** W3C. [WCAG 2.2](https://www.w3.org/TR/WCAG22/), criteria 1.3.1, 1.4.1, 1.4.10, 2.1.1, 2.4.3, 2.4.7, 2.4.11, 2.5.7, 2.5.8 and 4.1.3; [target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html). No conformance claim follows from this review.
- **P6.** web.dev. [Learn PWA: Caching](https://web.dev/learn/pwa/caching/) and [Installation](https://web.dev/learn/pwa/installation/). Platform behavior must be checked again for the selected implementation and supported devices.
- **P7.** Desruisseaux, B. (2009). [RFC 5545: Internet Calendaring and Scheduling Core Object Specification](https://www.rfc-editor.org/rfc/rfc5545), sections 3.6.1, 3.6.6 and 3.8. Event format, identity, time and alarms.
