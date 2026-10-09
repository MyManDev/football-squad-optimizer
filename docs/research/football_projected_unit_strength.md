# Private projected club-unit and replacement experiment

Implementation preparation for #1057, the first of six ordered families requested
by the owner. The remaining order is set-piece duties, tactical matchup, injury
minute roles, all-competition workload and score-state behavior. Each family gets
its own PR and cumulative checks. Actual combined native invocation follows real
predecessor merges in a separate step. This document is a proposal and implementation
record, not an accepted measurement protocol or evidence of forecasting gain.

## Inputs and boundaries

`features.football_unit_inputs` defines frozen, versioned source, attribute,
persistent player mapping, club-unit exposure and complete projected-state inputs.
`features.football_unit_catalog` accepts strict private UTF-8 JSON bytes and exact
schemas. Duplicate keys, Boolean identities, nonfinite numbers, conflicting
mappings, expired snapshots and information unavailable at the actual gameweek
decision cutoff are refused. Every fixture in one gameweek shares that cutoff.
Kickoff is not a substitute for the fantasy deadline.

Source receipts declare provider, logical source family, edition, raw-byte hash,
publication/capture/effective/expiry times and permitted model development. A
receipt is supplied evidence: parsing it does not independently establish its
truth or create permission. FM uses separately declared 1 to 20 attribute semantics
and explicit missingness. Different FM editions can share a logical family only
when declared definitions, provider, units and bounds remain compatible. Their
individual vintage and rights receipts remain distinct. No player name, row order,
age or approximate name match becomes a persistent FPL identity automatically.

`features.football_fm_attributes` is a separate private CSV byte adapter. It binds
the exact source hash, cutoff and declared FM trait-column mapping, requires a
persistent UID, preserves blank missing values and refuses ranges or ambiguous
duplicate ratings. It returns source-keyed attributes, not a name-derived FPL
crosswalk. The FM23 aliases, including `Nat.1` for Natural Fitness, are explicitly
declared by the caller. Research downloads have not been passed into a fitted model.

Historical observations contain both actual eleven-player club units, exposure
minutes, integer credited goal counts, a separate settled outcome receipt, and
paired reference units and baseline rates available at the historical deadline.
Goals refer to the same exposure interval. Overlapping intervals and duplicate
opposing copies are refused. A segment spanning a substitution must be split at
the substitution; player presence cannot be reconstructed from total match minutes.
Partial units after dismissals are not supported in this version. Published FPL
scoring position groups attributes; it is not a claim about tactical role.

Inference needs complete joint states of both clubs with positive masses summing
to one, or one complete deterministic paired state. Start marginals alone do not
identify this joint distribution. No joint teammate absences are manufactured.
Reference and projection sources are explicitly named. Full projection and
reference-pair identity receipts accompany the forecast.

## Model and mathematical connection

For an exposure of duration `t`, the supplied predecision baseline is `b`. A
reference-relative feature vector is `d = features(unit) - features(reference)`.
The club count mean is

```text
exposure = (t / 90) * b
E[count] = exposure * exp(beta . scaled(d))
```

The regularized Poisson fit receives `count / exposure` with sample weight
`exposure`. It has no intercept and uses a train-only weighted scaler without
centering, so `d = 0` reproduces `b` exactly. The fixed prototype regularization
is 0.1; this is not a selected or calibrated production value. Feature columns
include persistent player presence, position counts, declared attribute sums,
missingness and home interactions. Opposing orientation is trained coherently.
Fitting and prediction use sparse relative rows rather than an observation by
all-known-player dense matrix. The effect is an observational association, not an identified causal substitution
effect. Small synthetic fixtures cannot establish the contribution of a real
injured player or the value of that player's actual replacement.

For projected state `s` with supplied mass `w_s`, both goal rates are scored
before averaging:

```text
lambda_own = sum_s w_s * lambda_own,s
lambda_opponent = sum_s w_s * lambda_opponent,s
replacement_gap = projected mean rate - contemporaneous reference rate
```

`application.football_unit_experiment` explicitly composes the result with retained
conditional native v1 fixture components. Player goal and assist shares remain
unchanged; their total credited masses scale by the own-club rate ratio. This
preserves `sum(player goals) <= team goals` and `sum(assists) <= sum(goals)` before
eligibility. Native four-bin minute, residual and DEFCON heads remain fixed.

Clean-sheet exposure uses the nonlinear mixture directly:

```text
P(clean sheet) = sum_b>=60 minute_mass_b * sum_s w_s * exp(-lambda_opponent,s * minutes_b/90)
```

Using `exp(-average lambda)` here is incorrect. Native player minutes and unit
states are independent in this first version. Complete club XI states do not
establish a joint focal start/cameo/minute law. Later injury and score-state
families must carry a new explicit composition contract rather than silently
assigning correlations. Retaining the native residual also retains its saves,
cards and goals-conceded approximation; this family adjusts the named goal,
assist and clean-sheet components only.

The mixture carries its own private component identity. It is not labelled as a
native v1 artifact that assumes one Poisson rate. Immutable canonical result
receipts and component digests refuse altered rows at weekly aggregation. These
digests bind supplied inputs; they do not authenticate an external data provider.

The calendar proves scheduled player-fixture coverage. A missing scheduled
forecast is refused; a known blank week produces zero. Shared weekly eligibility
`a` is applied once, including a double gameweek:

```text
weekly expected points = a * sum_fixture conditional expected points
weekly appearance = a * (1 - product_fixture (1 - conditional appearance))
```

Thus a retained single-match appearance of 0.8 and captured eligibility 0.75 give
0.6, while two such fixtures give `0.75 * (1 - 0.2^2) = 0.72`. Values 0, 0.25 and
0.5 keep their separate semantics. This implementation adds no new calibrated
injury model and does not automatically declare all low flags absent.

One legal frozen fifteen is then evaluated by the existing bounded role search,
which includes legal XI changes, ordered reserves and captain/vice choices.
Official formation, autosub, cameo, captain fallback and chip rules remain in that
engine. Bank, squad, prices and club/position identities stay on copied native
inputs. No transfer, wildcard roster or multiweek action is added here. The exact
fixed-fifteen option requires the actual merge of #1056. Native combined usage
also waits for #1049, #1052 and #1055 as applicable; no unmerged implementation is
copied into this PR.

## Source use cases, ANN and evaluation gates

See [the FM source feasibility audit](football_fm_source_feasibility.md) for actual
downloaded candidate schemas, declared licences, hashes, PL gaps and date gates.
FM traits can supply a slowly changing skill prior for low-observation players.
Heading and Jumping Reach are distinct from GK Aerial Reach. Positioning and
Anticipation are distinct from actual defensive actions or a calibrated injury
state. The explicit model learns associations; it does not assign a hand-written
FM score multiplier. Set-piece duty, recent medical status, actual competition
schedule and live tactical role need their own current sources.

An ANN can later consume the same typed numeric attributes, missingness masks,
stable identity mappings and versioned causal context. Freeze feature order,
source families/editions, transformations, train-only normalization and model
identity per artifact. Sparse identity storage and declared feature semantics
keep the current head separate from a future embedding implementation. No ANN
is fitted here. If learned unit contributions become another model's inputs,
they must be generated out of fold or chronologically; in-sample fitted outputs
would leak target information into that model.

Actual training requires permitted exposure/events, authoritative historical GW
cutoffs, persistent crosswalks, declared missingness/coverage and a reproducible
predecision baseline for each historical interval. The supplied baseline must
itself be causal or out of fold, not fitted on that interval's future result.
Historical projected lineups may be used only if their predeadline availability
is proved. Later-published FM editions cannot be backfilled into earlier decisions
by calling them that earlier year's FM version.

Before any real comparison, the owner must resolve the existing #1004/#1009/#1016
population and reading decisions, including protected 2025-26 disposition. Record
which predecision source snapshots and seasons are admitted, then freeze chronological
development/validation/later untouched test blocks, primary rate and fantasy-point
metrics, missing-data policy, comparison and thresholds. Proposed comparisons are
accepted native model, identity-only unit head and identity-plus-permitted-attributes
head, followed by policy replay on the same fixed decision population. These are
questions for preregistration, not decisions made by this implementation.

## Verification record

All implementation checks use synthetic sources, exposure, projections and
temporary fixtures. No FPL archive outcome was read, no real football model was
fitted and no evaluation gain was measured. Strict parser tests cover raw byte
and schema errors, including UTF-16/32 auto-detection and huge numeric conversion.
Independent scoring tests check club allocation and the nonlinear clean-sheet
mixture algebra. A learned adjustment changes the selected keeper and agrees
with a separate keeper-role expectation. DGW cutoff, source/feature provenance,
mutated component rows and Boolean player identities have regression cases.
Default native component and existing role-engine regressions remain part of the
focused cumulative check. Final case, mutation and runtime counts are recorded
in the implementation PR and issue comment after the final source handoff.

No backend, live weekly run, public data, publication, queue, merge or deployment
is invoked. The source and fixture adapters are explicitly called private Python
boundaries; a production command and artifact reader integration are a later PR.
