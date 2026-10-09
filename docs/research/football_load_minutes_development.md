# Private all-competition workload and weekly minutes

Issue #1065 is family 5 of the owner's six ordered football experiments.
This preparation adds pure source, model and private application boundaries.
Actual source admission, fitting, measurement and combined native invocation
retain the issue's review, merge and owner protocol gates.

## Why player exposure matters

League history omits cup, European and international appearances. A club's
120-minute cup match does not assign 120 minutes to each squad player. Actual
player minutes and recorded starts, including a verified unused squad member,
need complete participation evidence. A player keeps accumulated exposure when
transferring or returning from international duty.

[FIFPRO's monitoring framework](https://www.fifpro.org/en/articles/2024/06/about-mens-player-workload-monitoring-platform)
separates match load, competition formats, international travel and rest. That
motivates separate feature channels rather than a hand-set fatigue deduction.
[A prospective 27-team, 11-season study](https://pubmed.ncbi.nlm.nih.gov/23851296/)
found congestion associated with muscle injury while team-performance effects
were limited. [A player-level congestion study](https://pubmed.ncbi.nlm.nih.gov/26682867/)
explicitly measured an inter-match interval from the end of play to the next
kickoff. These studies support measurement definitions and candidate inputs;
they do not supply calibrated FPL appearance values or causal treatment effects.
Their measured thresholds are not automatic exclusion rules in this model.

## Source admission and coverage

| Candidate | Verified public metadata | Remaining admission evidence |
| --- | --- | --- |
| [OpenFootball England](https://github.com/openfootball/england) and [Europe](https://github.com/openfootball/champions-league) | CC0 database declaration. EPL, FA Cup and EFL Cup filenames occur in each 2020-21 through 2024-25 England folder. European files cover CL/EL in 2020-21, then CL/EL/Conference through 2024-25; qualifying files occur in 2024-25. | Audit actual complete fixtures and UTC kickoff precision. Establish original historical byte publication before each decision. No player-minute evidence. Current 2026-27 England metadata lists EPL/Championship only and Europe has no 2026-27 folder. |
| [football-data.org](https://www.football-data.org/coverage) | Competition catalogue and [match schema](https://docs.football-data.org/general/v4/match.html) expose UTC kickoff, team/person identities and lineup/substitution fields. | [Pricing](https://www.football-data.org/pricing) separates free fixtures, paid lineups/substitutions and a history package. Record the exact combination of competition, historical participation entitlement and model permission. No account entitlement is assumed. |
| [OpenLigaDB](https://beta.openligadb.de/) | ODbL data declaration and [Swagger](https://api.openligadb.de/swagger/v1/swagger.json) calendar fields; current homepage lists EPL 2026-27. | Community league presence does not certify complete coverage. No complete player participation endpoint established; the sample-code licence is separate from the data licence. |
| [StatsBomb Open Data](https://github.com/hudl/open-data) | [Current competition metadata](https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json) has EPL 2003-04/2015-16 and selected international tournaments. | Requested EPL seasons and complete cross-competition player histories are absent. Admit the separate data agreement and authentic historical publication clocks; repository update time is a revision time. |
| [Wyscout research release](https://figshare.com/articles/dataset/Events/7770599) | CC BY 4.0 event release described in its [primary paper](https://www.nature.com/articles/s41597-019-0247-7). | Covers 2017-18 leagues, World Cup 2018 and Euro 2016, outside the requested development seasons. Useful schema reference only. |

OpenFootball metadata was inspected at England commit
`b17e8f01707d83d2ce1790c14d4a5eeb35987825` and Europe commit
`abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef`. File presence alone never satisfies
participation or contemporaneous publication admission.

[football-data.co.uk's current conditions](https://football-data.co.uk/data.php)
exclude its free files from commercial or automated data-training products.
This preparation does not admit them. An alternative permission would require
its own explicit evidence. No source registration, paid subscription, real
match-file download or historical outcome reading was performed here.

Three source inventories have different roles:

1. Historical physical participation, settled and published before the decision.
2. Future calendar opportunities frozen as known at the decision.
3. Expected competition/fixture coverage and dated persistent identity mappings.

Each needs original bytes, a digest, source/version and causal publication and
capture clocks. Coverage must span the declared 28-day interval and competition
population. Verified empty coverage is zero; missing competition coverage is an
enabled-input refusal. Unknown minutes or starts remain nullable aggregates
with observation counts and explicit missingness. They never become unused
bench facts. Aliases from multiple providers must resolve to one canonical
match; conflicting clocks, identities or exposure refuse.

Physical added/extra-time exposure remains distinct from FPL credited minutes.
Actual recovery requires an explicit played-exit or match-end timestamp. A
kickoff-to-kickoff interval is a separately named proxy. Actual journey,
predecision planned journey and venue-distance proxy remain separate channels.
Coordinates can support geographic distance but do not establish flight time,
arrival or the player's itinerary. [Wikidata structured data](https://www.wikidata.org/wiki/Wikidata:Licensing)
is CC0, with venue identity and coordinate vintage still needing admission.

## Learned complete-week law

The native offset supplies an immutable coherent joint law `P0(s)` for the
whole player week. Each target fixture has seven native states: absence, three
start-duration bins and three cameo-duration bins. At most three target
fixtures give at most `7^3 = 343` vectors. The input binds original native
version, support minutes, marginal probabilities, calendar and a genuine
out-of-fold or prospective predecision receipt. Fitting on a baseline that saw
its own outcome remains inadmissible.

For a feature/state vector `Psi(s, x)`, fit the regularized categorical model:

```text
Ptheta(s | x) = P0(s) exp(theta . Psi(s, x)) / Z(x)
Z(x) = sum_u P0(u) exp(theta . Psi(u, x))
loss = sum_weeks [log Z(x) - theta . Psi(observed, x)
                  - log P0(observed)] + l2 * ||theta||^2 / 2
gradient = sum_weeks [E_Ptheta Psi - Psi(observed)] + l2 * theta
q_week = sum_{s with any positive role} Ptheta(s | x)
p_fixture(f, k) = sum_{s: s[f] = k} Ptheta(s | x)
```

Weekly any-appearance and role/duration statistics connect exposure to both
appearance and minutes. Ordered within-week state exposure can inform later
fixture roles using known gaps. Future calendar opportunities are rotation
inputs, never guessed future actual minutes. There is no hand-set load penalty
and no calibrated flag fraction in this learner.

Training fits preprocessing on admitted training rows only. Named numeric
channels retain missing masks and units; fitted parameters and source receipts
are immutable. Stable normalization retains structural zero native support.
Zero coefficients reproduce the declared normalized native law. Near-unit
source mass is normalized within a strict accepted tolerance and its original
input digest remains recorded. No epsilon creates an unsupported observed role.
A blank week has its one empty zero-appearance state.

The versioned inventory has 53 source channels. Training design has 735
parameters: seven weekly role statistics crossed with a 99-value context,
24 target-fixture gap/opportunity interactions and 18 ordered-state exposure
interactions. The context contains 47 non-fixture channels with value and missing
indicator, an intercept and four positions. Packed fitting stores the context
once per player week plus seven role counts and 42 per-state interaction values.
An independent dense-algebra oracle checks the packed objective and gradient;
the bounded three-fixture example uses over eight times less design storage.

The feature response estimates predictive associations conditional on the
native offset. PL-only history already inside the native model remains recorded
in that offset. A future combined arm must declare incremental non-PL channels
and factorial ablations, preventing unexplained duplicate workload effects.

## Scoring and lineup boundary

The private adapter derives fixture moments from the same complete-week law.
It updates expected minutes once, reweights each native full-club credited goal
and assist allocation by new versus old exposure, and renormalizes the complete
recipient population. Native physical goal intensity and credited club totals
remain fixed. No extra attacking bonus is added. Clean-sheet and defensive
contribution moments integrate each supported duration before scoring; using
the mean duration inside nonlinear functions is incorrect. Existing residual
policy and resources remain fixed. Unsupported exposure and physically
impossible individual goal-plus-assist first moments refuse.

Standalone family 5 retains one externally supplied legacy eligibility `e`,
bound to its own immutable original-capture receipt:

```text
expected_week_points = e * sum_f clip(fixture_points_f)
effective_week_appearance = e * q_week
```

It does not union learned fixture marginals and does not apply eligibility again
inside every fixture. Exact supplied legacy control stays separate from the
zero-coefficient native ablation. A dependent native week needs an explicitly
matching causal served reference; a product-union comparator cannot silently
stand for that different law.

Disabled composition consumes the finite captured weekly appearance value as
served, including arbitrary dependent DGW control. It does not reconstruct a
joint law from marginals or inspect workload/model inputs. Supplied weekly
points still reconcile to native fixture clipping times the captured eligibility.
Enabled control separately binds the explicit native joint receipt. Original
frame receipts bind columns, values, indexes, dtypes and metadata. Accepted
unknown-role null representations have distinct missing-kind tags in the digest;
returned frames retain their original values. Scoring/resource nonfinite values
still refuse. Target FPL kickoffs must belong to the declared July-to-June season.

The existing bounded expected-lineup engine selects legal fixed-fifteen XI,
ordered bench and captain/vice roles using these weekly values. Inventory,
chip, hit, restrictions and locks remain bound to the native resource receipt.
It is not global transfer optimization. The scorer retains its independent
player-week and supplied conditional-point approximation. Separate predicted
player roles do not establish a legal joint club eleven, correlation between
teammates or a joint scorer/assister event generator. Card-only scoring outside
positive-minute participation remains outside that scorer's event contract.

## Actual combined invocation and later ANN

After actual applicable predecessor merges, a separate reviewed invocation can
consume family 4's immutable whole-week flag law as the baseline, or fit one
joint flag/load model under an accepted protocol. It must preserve DGW
dependence and apply learned eligibility once. Two separately learned absence
values must not be multiplied. Family 1 unit strength, family 2 duties and
family 3 tactical allocation require explicit order, consistent native mass
accounting and cumulative regression evidence after their real merges.

An ANN arm can later consume the named workload channels, observation counts,
missing masks, source age and licensed dated FM stamina/natural-fitness traits.
Keep train-only preprocessing and grouped chronological GW/season splits;
freeze architecture/tuning before the later untouched reading. Source rights,
real temporal identity, cohort/coverage, population, arms, metrics and threshold
decisions remain #1004/#1009/#1016 and #1057 gates. Protected 2025-26 outcomes
are excluded. No actual gain, real-data model training or live integration is claimed.

## Prepared implementation evidence

Focused checks pass 445 distinct cases: 140 source, 58 model, 70 private
integration and 177 existing native minute, availability, component and lineup
regressions. The initial 67 integration cases passed, then the corrected
inventory fixture and 36 affected cases verified the isolated owned-fifteen
refusal and three additional accepted unknown-role representations. These
overlapping runs are not added to the distinct total. Only focused local files
ran; no full local suite or actual forecast was invoked.

Eighteen isolated copied-source faults produced 21 failing behavioral checks.
Every selected original baseline passed, no mutant failed in setup, and final
SHA256 values of all three original source modules equal their starting values.
The probes cover byte hashes, correlated native receipts, causal outcome
preflight, unknown exposure, physical exit/finalization, complete target
crosswalks, extra opportunities, native normalization, missing masks, ordered
exposure, common GW clocks, once-only allocation/eligibility, original owned
inventory, explicit served joint reference, club mass and dependent disabled
control. The causal preflight test uses unopened full-body and outcome sentinels,
so an unrelated calendar refusal cannot mask a missing header guard.

The independent source-to-fit-to-fixture-to-weekly-to-role oracle verifies
physical exposure, derived minute marginals, conserved native credited G/A,
seven-state nonlinear CS/DC and once-only weekly eligibility. A separate
appearance-world scorer checks official greedy reserve formation and
captain/vice fallback. Correlated DGW, explicit BGW, structural zero/one support,
chips, locks, exact served control and workload-sensitive XI/reserves/captain
are covered. A legally shaped same-club roster swap isolates the original-owned
inventory guard from the separate maximum-three-club refusal.

Ruff and formatting pass all seven Python files. Strict mypy passes three
source modules. All six architecture import contracts pass. No backend, server,
weekly operation, public data or member copy is involved.

Three invented runtime samples use 80 raw-source/raw-outcome training player
weeks from 2024-25, 66 target players, 88 fixture-player rows and eight paired
club-fixture sides. Fit times are 4.615 to 4.826 seconds, composition 1.103 to
1.115 seconds and bounded 128-role selection 0.515 to 0.542 seconds, under
concurrent focused-test load. Original frame hashes and the captured owned
resources remain unchanged; all samples publish the same fitted model digest.
These are implementation timings, with no real-population speed or gain claim.
