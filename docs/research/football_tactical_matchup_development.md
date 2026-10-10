# Private tactical matchup development

Issue #1061 step 1 prepares the third of the six ordered football families. The
private candidate learns how named attacking traits and observed club style
interact with named opposition defending traits and style. It adjusts paired team
goal intensities and the recipients of credited goals and assists. There is no
attribute-to-points lookup, fixed quality bonus or production caller.

## Invocation and boundaries

`read_tactical_projection` reads original projection JSON bytes with a verified
`TacticalSource`. `read_tactical_observation` independently binds final physical
goals and actual FPL credits. `TacticalMatchupModel.fit` accepts admitted immutable
observations and explicit cutoff, development seasons and target identity.
`compose_tactical_candidate` binds a complete native roster, fixture calendar,
native components, captured eligibility and resource bundle. The separately
invoked `plan_tactical_fixed_fifteen` selects roles for a supplied legal fifteen.

No public forecast, request, worker, planner default or weekly command imports
this candidate. Step 2 waits for actual #1058, #1060 and #1056 merges and a separate
named native integration review. This worktree does not copy those unmerged
implementations. Its existing role engine is the bounded neighborhood search with
at most 128 evaluations; exact fixed-fifteen enumeration is a later integration.

The native roster preserves player/team/club identity, FPL position, purchase and
sale price tenths, every optional resource column and attrs. Captured resources,
source frames and resulting frames have canonical receipts and hashes. Mutation
of a candidate frame, attrs or resources refuses before role selection. A complete
calendar proves both paired fixtures and blank player-weeks; an empty global week
requires explicit `covered_gameweeks` metadata. Every native component and calendar
row binds the same original decision cutoff. Source capture after that cutoff
cannot be relabelled as information held before it.

## Facts, units and identities

Six style counts are separate nullable observations: cross attempts, headed
shots, throughball attempts, fast-break shots, pressures and high-pass attempts.
They become rates per 90 observed fixture minutes. Each style window binds its
season, actual fixture identities, kickoff/final clocks, complete coverage,
provider mapping, definition version and original source bytes. Missing counts
or coverage cannot become observed zeros.

Sixteen named native 1..20 traits are preserved: heading, jumping reach,
goalkeeper aerial reach, pace, acceleration, anticipation, positioning, marking,
tackling, strength, off the ball, crossing, passing, vision, decisions and
technique. Explicit tactical roles are separate from FPL scoring positions. A
DEF who played a different tactical role does not acquire one by inference from
the scoring label. Traits bind original provider/version identity, reviewed
FPL-person and club mapping, validity interval, permission evidence and cutoff.
Required traits missing from positive exposure refuse. Structural zero-minute
players do not receive an invented average ability.

Each fixture supplies a complete shared predecision state distribution over both
clubs. Each state contains complete paired projected minute/role profiles,
baseline paired intensities and native goal/assist shares. The reader validates
bounded rosters, minute/exposure limits and share closure; actual legal on-field
units and substitution chronology remain projection-source admission evidence.
Start marginals, independently sampled
teammates and the subsequently observed starting XI cannot substitute for these
historical states. Identical states can be split into smaller weights without
changing likelihoods, transformations or predictions.

Declared nonnegative weights must sum to one within the explicit 1e-12 input
tolerance. The model normalizes that admitted roundoff consistently for training
transforms, mixture likelihoods and prediction. Fitted receipts record the
effective weights and their policy; original projection bytes/digests remain
unchanged. This numerical normalization does not repair unsupported distributions.

Original-byte readers refuse duplicate JSON keys, nonfinite numbers, unsupported
versions, unexpected fields, malformed identities, duplicate source mappings,
invalid dimensions and incompatible event totals. Protected 2025-26 and target
labels are checked before outcome access. Features must be held by the original
decision; final labels must be independently available by the training cutoff.
Training observations in the same season/gameweek must share one original decision
clock, including both fixtures of a double week.

## Learned paired rates

For fixture f, shared state z with prior weight w[f,z], club c and native rate
lambda0[f,z,c], the learned rate is

```text
lambda[f,z,c] = lambda0[f,z,c] * exp(x[f,z,c] dot beta)
P(Yhome,Yaway | f) = sum_z w[f,z]
    * Poisson(Yhome; lambda[f,z,home])
    * Poisson(Yaway; lambda[f,z,away])
loss(beta) = -sum_f log P(Yhome,Yaway | f) + alpha * ||beta||^2 / 2
```

The two goal counts share the same state. Labels are not repeated as independent
observations in every projected state. A zero native rate remains zero; positive
observed goals need positive joint-state support. Log-sum-exp evaluates mixtures,
and analytic gradients use the physical-pair posterior state weights.

The 46 named team features include separate own/opposition style, native
goal-share-weighted attacking attributes, assist-share-weighted delivery
attributes, minute-weighted opposition defending attributes and goalkeeper aerial
reach. Explicit pair and three-way interactions cover, for example, own crossing,
own heading and opposition heading. Interaction coefficients are learned rather
than assigned football quality weights. Their biological or causal interpretation
is not established by this synthetic implementation proof.

## Learned credited recipients

The goal and assist heads each use a full-club native allocation offset. For
positive native share s0[i,z], recipient features v[i,z] and fitted gamma,

```text
s[i,z] = s0[i,z] * exp(v[i,z] dot gamma)
    / sum_j s0[j,z] * exp(v[j,z] dot gamma)
P(credited count vector C | physical pair, observed credited total N)
    = sum_z P(z | physical pair) * Multinomial(C; N, shares[z])
```

An entire club credited-count vector is one conditional observation with its
observed total held fixed. The model does not fit a law for the credited total.
Both heads reuse the fitted physical-pair posterior. They are separate recipient
marginals and do not supply a joint scorer/assister generator. Each has its own L2 penalty and learned
named recipient features. Native shares already contain the state minutes and
are not multiplied by minutes again. A zero native share stays unsupported.
Positive forecast credit mass without any admitted historical credited events
refuses the corresponding enabled head.

For scored fraction r[z] and assist fraction a[z], player means are

```text
G[i] = sum_z w[z] * lambda[z] * r[z] * goal_share[i,z]
A[i] = sum_z w[z] * lambda[z] * r[z] * a[z] * assist_share[i,z]
CS[i] = sum_z w[z] * I(minutes[i,z] >= 60)
    * exp(-opposition_lambda[z] * minutes[i,z] / 90)
```

Intensity and allocation are integrated inside the same state. Multiplying their
separate averages would lose covariance. Clean-sheet exposure is also nonlinear;
the model does not substitute exp of an average opposition rate. Full-club goal
and assist mass is checked against each state's credited totals. A player's
combined G/A marginal cannot exceed the physical event intensity; an unsupported
allocation refuses instead of producing incoherent points.
This is an intended enabled-path refusal even when the native shares passed:
learned recipient concentration can violate the individual physical event bound.
No clipping or recipient renormalization is authorized by this version. Exact
disabled/control composition remains available without that learned allocation.

## Fitting and receipts

Deterministic L-BFGS-B starts from zero and fits penalized mixture losses. These
losses need not be globally convex. Finite successful convergence is required;
method, initial state, objective, iterations, evaluations and gradient magnitude
are recorded. No global optimum, identifiability or predictive gain is claimed.

Feature transformations use training rows only. Team moments use prior shared
state weights with half the fixture weight per side. Recipient moments use prior
state/native-share weights, without outcome-dependent preprocessing. Observed
columns that are constant, or whose weighted spread is at most 1e-12 of their
largest magnitude (binary roundoff of a constant), retain unit scale; dividing by
roundoff would turn a later real difference into an overflow refusal. Fitted
arrays are backed by immutable bytes; metadata includes named features,
transforms, parameter vectors, sources, rules, training identities and
decision/label clocks. Failed refits preserve the prior fitted snapshot.
Composition requires one unchanged snapshot throughout control binding and
learned predictions.

## Native component replacement and decisions

Before any learned replacement, beta/gamma-zero output must reproduce the native
full-roster paired rates, G/A/CS marginals and four-bin minute, appearance and p60
moments at the common cutoff. Partial roster control, different native decision
time, repeated eligibility and calendar/projection gaps refuse. Explicit disabled
and control calls preserve native numeric components; disabled calls do not access
the model or tactical projections.

Learned mode replaces only paired rate fields and expected player G/A/CS. Native
minute, defensive-contribution and residual fields remain the scoring basis.
The fixture score is recomputed with the native scoring rules and fixture clip.
Retained residuals are not recalculated as saves, goals conceded, penalties or
bonus from the new intensities; those channels need their own accepted residual
decomposition and calibration before an expanded claim.

Fixture scores then aggregate to player-week expectations. Captured eligibility
is applied once per player-week after fixture scoring, including a double week.
The effective weekly appearance is `a * (1 - product(1 - q_fixture))`, using the
inherited conditional fixture independence contract and one shared eligibility `a`.
Shared tactical states are within each paired fixture; this union does not
establish cross-fixture minute correlations. Blank weeks remain zero. The supplied
legal fifteen retains prices,
club limits, bank/transfer/chip resources, and explicit captain, vice-captain,
reserve and role restrictions. The accepted bounded expected-lineup scorer decides
roles under its independent player-week positive-minute participation contract.
The shared tactical states determine fixture scoring; this role adapter does not
claim correlated-player autosub optimization. This preparation changes
roles, not squad acquisitions or the default transfer planner.

## Synthetic validation evidence

199 source/model and raw-source integration cases pass. An independent
oracle reads original synthetic JSON, fits 12 observations with 54 goal and 18
assist credits, verifies learned paired rates and recipient allocation, recomputes
state-integrated clean sheets, and checks weekly expected points and legal role
utility by independently enumerating the appearance worlds. Against the native
control, the learned matchup changes the selected XI, captain and ordered
reserves under the supplied scoring contract. Changed opposition defending
traits alone change the selected captain. There is no measured real-data
improvement.
The committed unit tests now include a present outfield player at 75 minutes,
an independent posterior-weight recipient refit for each head compared with a
prior-weight refit, and a nonzero fitted model's zero-attacking-channel path.
They pin the minute-sensitive clean-sheet exponent, fitted physical-pair
posterior and actual replacement invocation rather than only a control shortcut.

The synthetic native rows are constructed from the synthetic projection. This
checks the binding contract and arithmetic, but does not prove that an actual
independent native producer can supply a TacticalProjection. That producer remains
a step 2 precondition with its own chronological basis and admitted source.

Coverage includes malformed original bytes, identity/time/coverage refusals,
forbidden/target labels before access, full fitted receipt immutability and failed
refit atomicity, analytic likelihood/gradient checks, zero/missing channels, state
splitting and side reversal, native minute/control binding, exact disabled/control
fallback, fixture clipping, DGW eligibility, explicit BGW coverage, resource/attrs
tampering, chips, hits and role restrictions. The independent audit found and
fixed stale native decision acceptance, uncaptured requested gameweeks, differing
historical same-GW decision clocks and admitted-roundoff state mass drift.

Private local audit observations reported ten copied-source faults causing 20
behavioral test failures: source hash,
strict final-source clock, historical common clock, weight normalization, assist
fraction, shared-state nonlinear clean sheets, native control, DGW eligibility,
frame/attrs receipts and resource bundle. All original source hashes remain
unchanged. Their gitignored logs are not reviewable evidence in this PR. The
committed source, model and integration tests supply the reproducible assertions.

105 existing native component, fixture scoring, expected-lineup, forecast-week
and publication cases pass, with one existing optional research-bo skip. Ruff
check/format passes seven Python files, strict mypy passes all three new source
modules, and all six import contracts remain intact. No full local suite ran.

Three separately invoked synthetic timing samples cover 67-player full rosters,
three or four paired fixtures and six or eight shared states. Fit takes
0.370 to 0.440 seconds, component/weekly composition 0.131 to 0.170 seconds and
fixed-fifteen roles 0.038 to 0.041 seconds, with 128 role evaluations per sample.
These are private local timing observations, unverified by committed artifacts.
These small fixtures
do not establish a production request budget or large-source training capacity.

## Provider and FM feasibility

[Sports Interactive's attribute definitions](https://community.sports-interactive.com/sigames-manual/football-manager-2024/players-r4958/)
give distinct meanings to heading execution, jumping reach and goalkeeper aerial
reach. Defensive positioning differs from attacking off-the-ball movement;
passing execution differs from vision, and acceleration differs from pace. The
candidate preserves those distinctions and does not turn FM ratings into a
calibrated FPL participation estimate.

[Opta event definitions](https://www.statsperform.com/opta-event-definitions/) and
[Hudl's glossary](https://support.hudl.com/s/article/event-data-glossary-player-metrics?language=en_US)
require explicit provider mappings. Crosses may be separate from general passes;
pass height does not prove a long pass, and a short possession does not alone
establish a fast break. Pressure counts need known coverage and exposure. These
examples motivate separate versioned facts; they do not supply our data rights.

[StatsBomb's pass-height analysis](https://statsbomb.com/articles/soccer/an-overview-of-pass-heights-in-the-premier-league-english-football-league-and-scottish-premiership/)
illustrates style variation. Its
[heading analysis](https://statsbomb.com/articles/soccer/introducing-hops-a-new-way-to-evaluate-heading-ability/)
also motivates accounting for opposition and exposure before interpreting raw
duel outcomes. Native football_history does not contain the required tactical
events. The [open-data competition inventory](https://github.com/hudl/open-data/blob/master/data/competitions.json)
does not establish complete PL tactical coverage for our 2020-21 through 2024-25
development seasons.

The owner's descriptive FM catalog is private and is not a review artifact in
this PR. Its reported counts, traits and loader results are not independently
verifiable from the committed files here. FM25 was
[officially cancelled](https://www.footballmanager.com/news/development-update-football-manager-25-1).
No actual catalog table is admitted for fitting in this PR. Missing
goalkeeper traits cannot silently enable the aerial tactical channel. A version
name, public upload date or current download date is not an authenticated
historical database snapshot. No real FM rows or FPL outcomes are fitted here.

The test fixture imports the accepted native scoring helper only to construct
its synthetic native basis. Candidate scoring and role comparisons also have
independent arithmetic/world oracles; this is not a public source producer.
The private raw-point check mirrors the accepted native season law and refuses
drift. Consolidating that law into an existing public prediction API needs a
separate reviewed change after the accepted merges, rather than a silent shared
runtime edit in this private-source step.

## Real source and evaluation gates

The final #1061 finish box remains open pending Ibo/designated approval and actual
permitted implementation/predecessor/native-integration merges. Before actual
fitting or readings, record these decisions and evidence on the issue:

1. The permitted historically timed event/style provider, complete fixtures,
   numerator/exposure definitions and reviewed mapping versions.
2. The actual predecision complete paired projection source, native rates,
   allocations, minutes and common cutoff receipts for training and inference.
3. Independently final physical goals and FPL-specific credits with the actual
   rules versions. Provider assist totals cannot replace FPL assists.
4. Admitted FM versions, original-source/model-use rights, authentic vintage,
   temporal FPL-person/club crosswalk and missing/aged coverage treatment under
   #1057.
5. Accepted population, chronological folds, primary metrics, frozen thresholds
   and a later untouched reading under the existing #1004/#1009/#1016 decisions.
   Protected 2025-26 remains excluded.

ANN development is a later separately approved comparison. Named nullable facts,
missingness, identities, source versions, cutoffs and fitted transformations can
be reused, with all preprocessing learned on training folds. A random player-row
split or today's FM snapshot cannot establish historical forecasting validation.
No member-facing UI, probability copy, real weekly run or measured gain is added.
