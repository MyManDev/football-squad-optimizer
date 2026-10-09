# Learned flagged-player participation and minutes

This is family 4 of the owner's six requested football feature families, tracked in
#1063 under #1012. It prepares an explicitly invoked private experiment. No existing
producer, recommendation route, weekly operation, public file or member page calls it.
Real source fitting, measurement and combined native integration remain separate gates.

## Source facts and admission

The editorial values 0, 25, 50, 75, 100 and null are separate categories. None is a
duration, a calibrated empirical appearance estimate, a regulatory ban or an automatic
bench instruction. Missing required source fields refuse; explicit null is retained.
Source status and news state are separate facts. A cameo still blocks an autosub.

[Official FPL team-news guidance](https://www.premierleague.com/en/news/2176502)
distinguishes doubts, returns, suspension and parent-club loan restrictions, with updates
before each deadline. These causes cannot be inferred from the percentage alone.
[The maintainer data dictionary](https://github.com/vaastav/Fantasy-Premier-League/blob/master/DATA_DICTIONARY.md)
names distinct this-round and next-round fields. There is no admitted official API
calibration contract for their numerical interpretation in this experiment.

`football_flag_captures_v1` is a strict private source transport, not a claim that FPL
publishes this schema. Original supplied transport bytes, their hash and the declared
permission/mapping/native-basis/calendar references are retained. A real import must
also retain the actual upstream bytes, transformation version and reviewed admission
evidence. A string saying permission or out-of-fold is not proof of either.

The reader binds persistent player identity, season, FPL scoring position, target event,
the common decision and deadline, complete fixture coverage and original native basis.
It chooses this-round or next-round only when the corresponding event ID matches the
target. It refuses another event rather than filling from whichever field is nonnull.
The latest unmodified next-round label is also retained separately for the accepted
legacy rule. Enabled composition reproduces the default legacy status/next-round
multiplier from those same source facts and binds it to the supplied served comparator.
A learned this-round label and a distinct legacy next-round label remain distinct.
Nondefault legacy availability configurations refuse this comparison version.
Archive capture precedes or equals archive publication, which must precede decision.
News timestamp must not follow capture. News age dates the news entry; it does not date
the last numeric flag change. Change is nullable unless sufficient comparable capture
history is actually covered. An incomplete history does not imply no change.

[Randdalf/fplcache](https://github.com/Randdalf/fplcache) is a promising source candidate,
with immutable dated cache paths and 2021 through 2026 directory metadata. The first
observed path is 18 April 2021, so early 2020/21 is absent. Directory presence is not
proof of complete deadline-by-deadline coverage. No cache bytes or outcomes were read
for this work. The [capture script](https://github.com/Randdalf/fplcache/blob/main/cache.py)
reformats API JSON and uses `datetime.today()` after fetching. The
[workflow](https://github.com/Randdalf/fplcache/blob/main/.github/workflows/cache.yml)
has a UTC schedule. Actual admission needs the exact revision, runner timezone and
Git publication clock; filename time alone is insufficient. The repository's software
license and [vaastav's upstream ownership notice](https://github.com/vaastav/Fantasy-Premier-League/blob/master/LICENSE)
do not resolve FPL data/model-use permission. Review the
[official FPL terms](https://fantasy.premierleague.com/help/terms) and establish source
permission before a real collector/import is enabled. No new collector is included.

The outcome transport `football_flag_outcomes_v1` needs a complete final per-fixture
minute and recorded start vector, plus source publication and final settlement clocks.
Starts are not inferred from duration. Weekly totals are insufficient to label DGW
fixture roles. Protected 2025-26 and the target/future GW are refused from external
headers before decoding outcome bytes; training repeats the guards before label access.
Each historical season/GW has one original decision clock. Its baseline must genuinely
be out-of-fold or prospective, fitted before that decision without its own label.

## One learned week law

The immutable native fixture law has seven states: zero, starter short/60/full, and
cameo short/60/full. Positive duration representatives stay inside their declared bins.
They retain the fitted native duration values. The new head learns state mass, and
therefore start/cameo and expected-minute changes; it does not invent new duration
values from a flag. Missing native starting roles refuse enabled replacement.

For fixture probabilities `p_f(z_f)`, let `h0 = 1 - product_f p_f(0)`.
The weekly hurdle is

```text
h = sigmoid(logit(h0) + beta' x)
```

`x` includes categorical label/status/news/position fields, nullable news age and
history change, capture age and fixture count. Missing masks are explicit. All numeric
centers/scales come only from admitted training observations. The source label is never
divided by 100 in this learned arm.

For the complete state vector `z`, excluding the all-zero vector:

```text
base(z) = product_f p_f(z_f)
C(z) = base(z) exp(gamma' phi(z,x)) / sum_(u != 0) base(u) exp(gamma' phi(u,x))
P(all_zero) = 1 - h
P(z != all_zero) = h C(z)
```

The six positive role/bin counts across fixtures are crossed with the week design in
`phi`. Native offsets keep their fixture-specific differences. A common week correction
can learn changes in nonappearance, starting role, cameo and long/short duration. This
first version does not include independently timed per-fixture later news: that needs
new source scope and coefficients, rather than applying postdeadline news retrospectively.

The hurdle minimizes Bernoulli negative log likelihood with native logit offset.
The conditional head minimizes whole-vector multinomial negative log likelihood only
on observed appearing weeks. Both use an explicit L2 penalty and deterministic bounded
L-BFGS-B, with finite convergence receipts and analytic gradients. Fitted transforms,
coefficients and hashes are published atomically after successful validation and fitting.
Arrays are backed by immutable bytes; failed refitting preserves the earlier full state.

For one to three fixtures the complete support has 7, 49 or 343 vectors. More than three
fixtures refuse explicitly. BGW is exact zero only with an explicitly complete covered
calendar. Native endpoints `h0=0/1`, unsupported observed native cells and numerical
underflow refuse in learned mode; no hidden epsilon opens structural support. A raw
zero label can still produce positive learned participation when native support permits
it. This is a source-label distinction, not an empirical claim about real zero flags.

The learned weekly appearance is exactly `h`. Fixture marginals are derived by summing
the same week law. Weekly union is not recomputed as if these learned marginals were
independent, and no second old eligibility multiplier is applied. This is especially
important for DGW and for any appearance sufficient to block substitutions.

## Explicit controls and scoring

Disabled and `control=True` modes return copies of the supplied original native
components and old served weekly numbers exactly. Those served numbers must bind
native fixture point sums and native weekly appearance union, with the captured old
eligibility applied once. Unsupported/malformed capture bases refuse even in control.

`zero_coefficients=True` is a separate flag-neutral native ablation. It recovers the
unflagged native independent-fixture law within floating-point roundoff. It removes
the old captured multiplier, so it is intentionally distinct from legacy served
control when that multiplier is below one. Metadata names these arms explicitly.

For a full captured real-club roster, the original native attacking share is proportional
to its per90 rate times original expected minutes. Therefore the retained-rate update is

```text
new_weight_i = original_share_i * new_expected_minutes_i / original_expected_minutes_i
new_share_i = new_weight_i / sum_j new_weight_j
new_G_i = original_club_G_total * new_G_share_i
new_A_i = original_club_A_total * new_A_share_i
```

This is not another minutes multiplier on already unconditional goals. Normalization
occurs across the complete source club, before selecting the owner's fifteen. Positive
club mass with no recipient support refuses. Native physical intensity and credited
club G/A totals remain fixed; totals close after replacement. A zero-minute native
recipient cannot silently acquire unsupported positive mass.
If concentrating separate G/A shares would give a player combined scorer/assist mass
above the physical club goal intensity, the candidate refuses. That necessary marginal
bound does not prove a valid shared joint scorer/assister event distribution.

For each fixture, appearance, expected minutes and 60-minute mass come from its seven
marginal probabilities. Clean sheets are summed as

```text
CS_i = sum_s p_i(s) 1[m_i(s) >= 60] exp(-opponent_lambda * m_i(s) / 90)
DC_i = sum_(s>0) p_i(s) NB_tail(threshold - 1; rate90_i * m_i(s)/90, dispersion_i)
```

The opponent rate and native per90 defensive contribution/dispersion remain fixed.
GK defensive contribution is zero. Defender threshold is 10 and MID/FWD threshold is
12. Nonlinear terms are evaluated at each duration point, never just at mean minutes.
Appearance points and native perappearance residual use fixture appearance once.
Native season-specific goal coefficients are retained, including GK 10 from 2024/25.
DEFCON scoring activates from 2025/26; raw fixture points are clipped at zero exactly
as in the native model. Weekly points sum those unconditional fixture points, without
another appearance multiplication.

The original native basis is checked by the accepted component identities as well as
the version/role/calendar/roster contracts. The adapter preserves full private metadata
and resources and hashes all supplied and resulting frames, indexes and attributes.
Downstream role selection refuses changed private outputs or resources.

## XI and reserve decision scope

The same legal fifteen reaches the accepted bounded `improve_expected_lineup` engine.
It receives unconditional weekly points and the whole-week any-appearance value. It
considers legal one-player XI swaps, ordered reserves and captain/vice choices, retaining
the incumbent if no visited alternative improves it. Hit/chip/lock/restriction resources
stay fixed. No transfer search or exhaustive optimum is claimed in this independent PR.
Combining the prepared exact engine in #1056 waits for its actual merge.

The independent tests enumerate appearance states and official legal substitutions to
check candidate scores, cameos, minimum-three-defender cases, GK replacement, captain
fallback, chips and locked actions. A flagged player may remain a starter when its
conditional points and reserve cover justify that choice, or move to the bench when
the reserve gives a better objective. No fixed flag threshold makes that choice.

The club allocation is moment accounting, not a joint match generator. It does not
certify a legal shared club XI, correlated teammate rotation or dependence of player
points on teammates' appearances. The accepted role scorer assumes independent
player-week appearances and fixed conditional point expectations. Card-only appearance
outside positive minutes remains outside that scope. These private research boundaries
are not added to member pages.

## Modular and real evaluation gates

Source, feature, model and experiment versions are separate. The pure source reader,
prediction head and application composition obey the repository layers. Other families
need not import this head; receipt-bound minute outputs can later enter one explicitly
reviewed composition. Actual #1049/#1052/#1055/#1056/#1058/#1060/#1062 and this implementation
merges precede a named combined native invocation and cumulative regressions.

FM Natural Fitness is a game recovery/physical-retention trait, as described by the
[official FM24 manual](https://community.sports-interactive.com/sigames-manual/football-manager-2024/players-r4958/).
It is not real current injury status. Later interactions with that trait, all-competition
workload, team strength or tactical roles require admitted authentic FM vintages and
temporal FPL crosswalks from #1057; unknown source/model permissions remain unresolved.
The 47 named trait values and missing masks can later feed a separate ANN model with
training-only preprocessing and chronological folds. No ANN is trained here.

Before actual development, the owner must accept the population, chronological folds,
baseline/control arms, appearance/minute/point and policy metrics, thresholds, protected
holdout and one later untouched read under #1004/#1009/#1016 or a matching explicit
protocol. The accepted existing participation protocol does not automatically approve
this replacement. Ibo/designated review and permitted actual merges are also required.
No real FPL outcome was read and no real model gain is claimed.

## Validation receipt

440 distinct focused cases pass: 152 source, 57 model, 60 integration and 171 relevant
existing regressions, with one existing optional research-bo skip. Source/model final
checks have 209 cases; the integration union includes the initial 58 and two new
bidirectional club mapping refusals, with overlapping inventory checks repeated after
that guard. The initial integration run had a Windows pytest-cache teardown permission
warning only; the final targeted checks and copied probes disable that cache provider.

Eleven deliberately injected faults in private module copies are caught by 20 independent
behavioral failures: categorical75, missing-category and missing-change masks, repeated
weekly hurdle, zero-control confusion, old multiplier again, mean-duration CS, repeated
minute exposure, contradictory row clock, altered frame receipts and altered resources.
Their original-copy baselines pass; no setup/import failure is counted as fault evidence.
Original source bytes remain unchanged by the probe harness.

Ruff check/format passes all seven Python files, strict mypy passes the three source
modules, and all six import contracts remain kept. Three invented 66-player samples
use 240 training weeks and 66 or 132 prediction weeks. Fit takes 0.383 to 1.137 seconds,
composition 0.500 to 2.418 seconds, and bounded roles 0.500 to 0.796 seconds at 128
evaluations, under concurrent focused local load. These are synthetic implementation
measurements, not realized FPL gain or production capacity. No full local suite, weekly
run or heavy slot was used.
