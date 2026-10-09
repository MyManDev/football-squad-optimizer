# Private football set-piece duties experiment

Issue [#1059](https://github.com/MyManDev/football-squad-optimizer/issues/1059),
step 1, implements a separately invoked source reader, learned allocation model
and native fixture/weekly/fixed-fifteen adapter. Existing live, served and member
routes do not invoke it. The implementation evidence is synthetic. It establishes
contract behavior and a bounded decision path, not measured FPL improvement.

## Source and causal input contract

`football_phase_inputs_v1` separates three historical documents:

1. `football_phase_baseline_v1`: predecision player positions and native goal/assist
   weights per 90 minutes.
2. `football_phase_credits_v1`: complete, disjoint goal events with final FPL scorer
   and assist credit, phase/rules versions, settlement time and credit evidence.
3. `football_phase_fpl_totals_v1`: independently supplied final FPL minutes, goals
   and assists for every captured club player.

Each has its own immutable UTF-8 bytes, exact SHA256, source/provider/version,
semantic kind, publication/capture clocks and admitted model-use evidence. Exact
byte hashes bind inputs before strict JSON parsing. Duplicate keys, unknown
fields/versions, nonfinite values, coerced identities and unsettled credits refuse.
A declared permission receipt records caller evidence; it does not authenticate
upstream rights.

The declared source season/GW, protected-season exclusion and source availability
are checked before outcome decoding. Settled event and totals source clocks must
be strictly before the training cutoff. Baseline bytes and historical duty captures
must be known by their own recorded decision, which cannot follow kickoff. Final
outcomes must become available after kickoff and strictly before training; their
source capture cannot precede the claimed availability. All observation headers
are checked before the model reads any event labels. The target GW, later GWs and
later seasons are excluded; an explicit season allowlist is required.
Current FPL ranks are never fetched to fill a historical fold.

Captured FPL priorities reuse the existing bootstrap reader. Payload inventory,
checksums, snapshot ID and fingerprint are reverified. Stable player codes map
through explicit season team IDs to persistent club codes. Each observation and
every projected state covers the full captured club roster, including zero-minute
players. Projection receipts bind decision, kickoff, fixture, opponent, venue and
native participation/mass basis. They contain an explicit complete distribution
of states, capped at 1,024, whose weights sum to one. Marginal start estimates do
not supply that distribution. Projected minute bins, appearance, 60-minute and
expected-minute marginals must agree with the retained native components.
Native fixture frames do not need an added decision column. An explicit
`decision_at` keyword supplies the original served-header clock when that column
is absent. When the column is present it remains binding; an explicit clock
cannot override it. Projection, calendar and downstream receipts retain that
same decision identity.

The 1,024-state cap does not support independent four-bin draws for a complete
25-player club. A later native producer must supply an admitted joint construction
with the same player marginals. A quantile coupling can use at most `3*N+1` states,
but choosing it imposes dependence and is not authorized by these synthetic tests.
Step 2 needs the accepted joint-state/coupling decision and its version/receipt
before real input construction. This version does not infer that coupling or
discard combinations to fit the cap.

The integration fixture contains 66 invented players across six source clubs.
Allocation uses all those club rosters before selecting the owner's fifteen. This
is a synthetic coverage check, not a claim about complete current PL coverage.

## Duties, phases and FPL credit

The official FPL site publishes regularly updated penalty, corner and free-kick
taker information. [Official set-piece guidance](https://www.premierleague.com/en/news/2231236)
The captured fields are `penalties_order`, `direct_freekicks_order` and
`corners_and_indirect_freekicks_order`. Positive ranks may tie; `null` means
published unknown. A missing field refuses. These ranks are neither event
frequencies nor ownership guarantees. The combined delivery field does not
separate corner duties from delivered free-kick duties.

Every received event has exactly one phase under `football_scoring_phase_v1`:
`penalty`, `direct_free_kick`, `corner`, `delivered_free_kick` or `other`. The reader
requires that exact declared version; it does not infer phases from total xG,
current duties or a generic provider assist. An admitted provider adapter must
document its mapping, including direct corners, passed penalties, rebounds and
the end of a set-play sequence. Delivered free kicks describe passed/crossed
free-kick sequences, not an inferred IFAB legal restart classification.

Opta distinguishes the penalty attempt, including passed penalties, from follow-up
shots. A direct free-kick attempt comes directly from the kick; a clearance
immediately returned into the area can remain a set-play sequence. A generic
provider play-pattern field therefore needs an explicit mapping. [Opta event definitions](https://www.statsperform.com/opta-event-definitions/)

FPL can credit the penalty/direct-free-kick winner when another player converts,
but not a self-assist. Winning a corner or throw-in does not itself earn an assist.
The penalty/direct-free-kick goal heads may learn taking-rank effects; their assist
heads do not treat that rank as the identity of the fouled/handball winner. Delivery
rank effects are learned separately for corner/delivered-free-kick assists, never
assumed to identify their scorers. [Current official FPL rules](https://www.premierleague.com/en/news/4661029)

FPL assist semantics changed in 2025-26, including treatment of defensive touches
and handball. Keep the actual rules version with every credited observation;
do not relabel older provider assists as current FPL assists. [Official assist rule changes](https://www.premierleague.com/en/news/4362187)
Scorer accreditation and final FPL/Opta assist decisions can require review, so TBC
is not zero credit. [Official accreditation and assist process](https://www.premierleague.com/en/news/4499344)

An own goal has no credited attacking scorer, although it may have a credited
attacking assist. Event IDs are unique within a club-fixture observation. Scorers
and assisters must be distinct, mapped, on-field players. Per-player event credits
must reconcile exactly to the independently hashed FPL totals, including explicit
zero totals. Complete phase coverage is required; missing coverage cannot become
a zero-event fixture.

## Learned allocation and conservation

Goal and assist heads are separate. For head `h`, phase `c`, player `i` and observed
fixture `j`, define exposure

```text
e[h,i,j] = native_weight90[h,i,j] * observed_minutes[i,j] / 90
logit[h,c,i,j] = log(e[h,i,j]) + beta[h,c] . x[h,c,i,j]
r[h,c,i,j] = softmax_over_positive_exposure_players(logit[h,c,i,j])
```

The conditional multinomial likelihood fits credited recipient counts, with L2
regularization. Position features are available to each head. Relevant heads also
use the published rank, an unknown-rank indicator, and counts of active higher,
equal and unknown-priority teammates. Coefficients are learned from observed
credits and exposure; no rank-to-frequency schedule is supplied. A credited event
with zero exposure refuses instead of receiving an invented floor.

For each head, empirical phase composition is learned from its own credited
counts: `pi[h,c] = N[h,c] / sum_c N[h,c]`. Goal and assist compositions can differ,
including assists associated with own goals. A wholly unobserved head refuses
positive forecast mass. Unobserved phases are not assigned invented frequencies.
Fit configuration, coefficients, feature names, counts and full source receipts
remain available through an immutable metadata API. Failed refits retain the
previous complete fit; successful refits replace all parameters and receipts together. Prediction
uses one immutable fitted snapshot.

For projected state `s`, use its supplied minutes to calculate `r[h,c,i,s]` and its
supplied native credited mass `m[h,s]`. The integrated allocation is

```text
E[h,i] = sum_s state_weight[s] * m[h,s] * sum_c pi[h,c] * r[h,c,i,s]
```

Multiplication happens inside each state. `E[m] * E[r]` is not substituted for
`E[m*r]`, and state minutes do not receive another appearance multiplier. Full-club
goal and assist masses are conserved separately before the owner's players are
selected. Each state also checks that one player's goal plus assist mass does not
exceed its physical club goal mass. The output declares separate scoring
marginals; it is not a joint goal/assist event generator.

The fixture adapter replaces native attacking counts and shares. It does not add
a second set-piece bonus. Physical team/opponent goal rates, minute support,
appearance, clean-sheet, DEFCON and residual components remain unchanged. Native
scoring algebra is recomputed, then clipped at zero per fixture. Zero attacking
mass creates no events and retains the native normalized share convention.

## Weekly eligibility and fixed-fifteen decisions

For one externally supplied player-week eligibility factor `a`, native fixture
expected points `mu[f]` after clipping and fixture appearance marginals `q[f]`:

```text
mu[week] = a * sum_f mu[f]
q[week]  = a * (1 - product_f (1 - q[f]))
```

This retains native fixture aggregation and applies eligibility once across a
DGW. It does not substitute per-fixture eligibility or redistribute mass after
selection. A synthetic value `a=0.75` checks mechanics; it does not calibrate the
meaning of a real published 75 flag. A BGW needs captured club identity and a
complete calendar proving no fixture; an omitted fixture row refuses.

Canonical receipts bind actual fixture values, calendar, projected decisions,
eligibility and weekly values. Native frame/roster metadata and nested resource
attributes are preserved and hashed. Positive season team IDs and persistent club
codes must map one-to-one. The fixed fifteen retains 2 GK, 5 DEF, 5 MID and 3 FWD,
with at most three players per persistent club. Price, bank, free transfers, chip,
hit and transfer-policy inputs are not searched or changed by role optimization.

The separately invoked role adapter searches the existing bounded neighborhood.
In the invented changed-duty integration example MID 12 replaces MID 11, captain
12 replaces captain 13, and the bench becomes `(2, 6, 11, 7)`. An independent
enumeration passes appearance outcomes through the official frozen-squad scorer.
This proves `bounded_fixed_squad_neighborhood_only`, not a globally exact search
or empirical football advantage. Combined exact role invocation waits for #1056.

## Residual and real-use gates

Native residual scoring retains penalty saves and misses. The official scoring
values are +5 and -2 respectively. No additional phase correction is added.
[Official scoring rules](https://www.premierleague.com/en/news/4661029)
A future separate miss/save head must subtract the same observed scoring terms
from residual training and update its version and consumers before adding them.

The primary rule pages above were read again on 2026-10-09. Source attribution
for the claims is explicit:

| Claim | Primary page and publication |
| --- | --- |
| Captured taker categories | [FPL set-pieces guidance](https://www.premierleague.com/en/news/2231236), regularly updated guidance; historical ranks still require original captured bytes |
| Penalty winner, handball, direct free-kick and no self-assist; penalty save +5 and miss -2 | [Official FPL rules](https://www.premierleague.com/en/news/4661029), published 18 May 2026, Scoring and Assists sections |
| The 2025-26 assist-rule change | [Official announcement](https://www.premierleague.com/en/news/4362187), published 18 July 2025; historical observations retain their own rules version |
| Review and finalization of assists | [Official process](https://www.premierleague.com/en/news/4499344), primary accreditation explanation |

These rule sources are separate from implementation proof. The committed
source/model/integration tests reconcile synthetic FPL credits, independent
scoring arithmetic and whole-week eligibility; they do not validate the truth
of a provider's future event feed. The private raw-point validator mirrors the
accepted native rule law and refuses drift. Consolidating that law into an
existing public prediction API needs a separate reviewed shared change after
accepted merges, rather than changing the live core in this private step.

Real source development remains gated by admitted licence/model-use evidence,
authentic publication/capture/vintage, reviewed temporal FPL player/club mappings,
historical duty captures and complete final phase/FPL credit coverage. The
inspected StatsBomb open catalogue does not establish the required PL 2020-21
through 2024-25 population or final FPL assists; public research availability does
not establish production rights. [Official open-data repository and terms](https://github.com/hudl/open-data)

The private FM20/FM23 package is descriptive source preparation. FM20 has no
established persistent UID; FM23 publication/patch/vintage and its FPL crosswalk
must be admitted before use. Uploader licence declarations alone do not establish
original source model rights. Family 2 does not infer a duty from FM ability or
consume those actual attributes in this step.

Unanswered owner population, chronological-fold, metric and threshold decisions
in #1004, #1009 and #1016 remain unresolved. Protected 2025-26 outcomes remain
excluded. A later untouched reading requires its accepted protocol. Actual native
combination waits for predecessor merges, including #1058 projected-unit intensity
and #1056 exact fixed-fifteen roles, then a separate named invocation PR with
Ibo/designated review and cumulative checks. No predecessor code is copied into
this fresh origin/develop step. No default route is switched by this document.

Modular source, feature, model, component and weekly versions keep later families
separate. A future ANN may receive the 47 admitted FM attributes with missingness
masks and contemporaneous role/lineup/opposition inputs. Identity/source clocks,
chronological folds and training-only transforms still apply. No ANN is trained
here, and no ANN or set-piece gain is claimed.

## Verification receipts

Only synthetic fixtures and focused/default regressions are implementation
evidence. The final source/model/integration run passed 177 cases in 9.45 seconds:
81 source cases, 56 model cases and 40 integration cases. Seven relevant existing
component, publication, bundle-switch and bounded-lineup files passed 138 cases
in 50.10 seconds, with one existing optional `research-bo` skip. This is 315
distinct passed cases, not a full local suite. Temporary fixture access required
the Windows test sandbox override; no server or real forecast was run.

Ruff check and formatting pass for all seven new Python files. Strict scoped mypy
passes for all three source modules. All six import contracts are kept over 456
files and 3,836 dependencies. No existing tracked source or default caller changed.

Eight faults were injected into separate private module copies. Original source
and test paths were never injected. Named assertions caught every fault:

| Private-copy fault | Expected failing checks |
| --- | ---: |
| Sequential labels before all-header preflight | 1 |
| Admit a later target gameweek despite its identity | 1 |
| Multiply recipient minute exposure twice | 1 |
| Apply penalty-taking rank to the fouled-player assist head | 2 |
| Apply DGW eligibility independently per fixture | 1 |
| Add attacking counts instead of replacing native counts | 28 |
| Ignore the explicit native decision cutoff | 1 |
| Decode settled labels whose source timestamp equals training cutoff | 4 |

The first four probes used the 55-case model baseline before the public metadata
accessor was added; that accessor has a separate passing prefit/postfit/frozen
receipt regression. The final four probes used the final 121-case source/E2E
baseline. This records 39 failing checks from eight faults, not 39 independent
faults. Private receipts retain source-copy hashes and the named failure cases.

An invented 18-observation fit took 0.157 seconds locally. Three complete parsed
projection-to-allocation-to-weekly-to-bounded-action calls over 66 source players,
six fixture sides and a fixed fifteen took 0.264, 0.269 and 0.265 seconds; median
0.265 seconds. Each action used its declared 128-evaluation budget. The old-duty
optimized expected score was 58.806726948236125; changed duties gave
64.73483106671277. Independent official four-world scoring agrees to `1e-10`,
and repeating the changed-duty call gave the same receipt and action. These
numbers describe invented fixtures on this PC, not a live advantage or production
performance bound. The search remains explicitly bounded.

These receipts do not replace real-source admission, evaluation decisions,
Ibo/designated review or the required actual merges. The issue remains open until
every finished condition is met or an owner explicitly disposes of a real-use gate.
