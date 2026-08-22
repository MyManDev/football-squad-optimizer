# The in-season blend on the development folds

Contract: `in_season_blend_benchmark_v1`  ·  model: `in-season-carry-over-v1`
Folds: **147**, `2021-22-gw02` to `2024-25-gw38`, seasons 2021-22, 2022-23, 2023-24, 2024-25.

The blend reads only what a capture carries — season-to-date totals, a carried
record, a price prior — because the archive publishes a season after it is played.
So it is scored against the archive-fed control above it and against ignoring the
season entirely below it. Every configuration shares one optimizer, so a difference
is the projection's. **The levels below are not comparable to the screening run's**,
which used its own bench weights.

## What each projection scored

| configuration | family | mean realized squad points | feasible |
| --- | --- | ---: | ---: |
| `control-fw05` | archive_fed_control | 53.7755 | 1.0 |
| `control-fw10` | archive_fed_control | 55.9796 | 1.0 |
| `carry-over-only` | floor | 43.1905 | 1.0 |
| `blend-m90-g6` | in_season_blend | 56.4694 | 1.0 |
| `blend-m270-g6-declared` **← declared** | in_season_blend | 56.966 | 1.0 |
| `blend-m540-g6` | in_season_blend | 56.585 | 1.0 |
| `blend-m1080-g6` | in_season_blend | 56.7143 | 1.0 |
| `blend-m270-g3` | in_season_blend | 56.8095 | 1.0 |
| `blend-m270-g12` | in_season_blend | 56.1293 | 1.0 |

## The declared configuration against each other one

Paired per fold, 90% season-aware moving-block interval.

| against | mean difference | interval | seasons positive |
| --- | ---: | --- | ---: |
| `blend-m1080-g6` | +0.2517 | [-0.7551, 1.9184] | 2/4 |
| `blend-m270-g12` | +0.8367 | [-0.3878, 1.8844] | 2/4 |
| `blend-m270-g3` | +0.1565 | [-0.8299, 1.0272] | 2/4 |
| `blend-m540-g6` | +0.381 | [-0.3946, 1.0884] | 4/4 |
| `blend-m90-g6` | +0.4966 | [-0.449, 1.1565] | 3/4 |
| `carry-over-only` | +13.7755 | [11.6803, 16.8639] | 4/4 |
| `control-fw05` | +3.1905 | [1.4014, 5.7143] | 4/4 |
| `control-fw10` | +0.9864 | [-0.7554, 3.6259] | 3/4 |

A positive difference means the declared blend scored higher. Against
`carry-over-only` the difference is what reading the season so far earns, and that
is the cleanest comparison here: the two differ only in whether the in-season term
exists, so nothing else can explain it. Against another blend the difference says
whether the declared weight sits at a local optimum on that axis. Against a control
it is the gap between a capture-only projection and one with the archive's rolling
features -- read with the caveat below, not as a clean win.

## The caveat that matters, before anyone quotes a number

`FITTED_OPENING_PRICE_COEFFICIENT` was fitted on opening-gameweek rows from 2020-21
through 2024-25 -- **the same seasons these folds evaluate**. It is therefore
in-sample here, and every configuration draws on it identically for players with no
usable history, so:

- differences between configurations that lean on it the same way are sound. The
  blend variants differ only in two weights, and the set of players priced from the
  prior is weight-independent, so the axis comparisons are unaffected.
- the **absolute levels are optimistic** for every configuration, including the
  controls.
- a **control-versus-blend** difference could partly reflect differing reliance on
  that constant rather than projection quality, because the two reach the prior
  through different conditions. Quantifying that exposure is the first thing a
  follow-up should do; it is not quantified here.

The production path refits the prior per fold on an expanding window
(`_price_coefficient`). This benchmark deliberately does not, so that every
configuration is scored on one fixed set of projection inputs and a difference is
attributable to the projection rule. That choice buys comparability and costs
absolute realism, and both halves of the trade belong in the record.

## Run it twice: which numbers hold still

Compared against `docs/in_season_blend_benchmark.json (#193)`, **3 of 9 configurations did not reproduce**, and the largest move was 0.2177.

| configuration | earlier | now | move | folds determined |
| --- | ---: | ---: | ---: | ---: |
| `control-fw05` | 53.7755 | 53.7755 | +0.0 | 147 |
| `control-fw10` | 55.9796 | 55.9796 | +0.0 | 147 |
| `carry-over-only` **<--** | 43.1497 | 43.1905 | +0.0408 | 70 |
| `blend-m90-g6` | 56.4694 | 56.4694 | +0.0 | 145 |
| `blend-m270-g6-declared` | 56.966 | 56.966 | +0.0 | 138 |
| `blend-m540-g6` | 56.585 | 56.585 | +0.0 | 123 |
| `blend-m1080-g6` **<--** | 56.932 | 56.7143 | -0.2177 | 77 |
| `blend-m270-g3` **<--** | 56.7755 | 56.8095 | +0.034 | 138 |
| `blend-m270-g12` | 56.1293 | 56.1293 | +0.0 | 136 |

The relationship is directional, not strict: both fully determined
configurations reproduced to the digit, and the two largest moves belong to the
two least determined -- but a configuration at 138 determined folds moved while
one at 123 did not, so determination bounds the risk rather than predicting the
outcome. The mechanism is #192, measured here rather than argued: where the
tie-break did not finish, the squad among equal-objective squads came from the
solver's search order, and a second run can pick a different one.

**So the weight axis is not resolvable at this precision.** The differences it
asks about are 0.16 to 0.84 points, and the movement between two runs of one
configuration reaches 0.22. The large comparisons are untouched: the floor moved
0.04 against a difference of 13.78, and both controls reproduced exactly.
## What this decides

Nothing on its own. It is a record, not a gate: `measurement_only` is true and
`gate_evidence` is false. The declared weights are **not** changed by it, because
changing a constant after seeing the surface is choosing the outcome. A better value
becomes a separate pre-registered candidate with its own gates.

On the question it was built to answer: the declared configuration is the highest
of the nine, and **every neighbouring weight is within about eight tenths of a point
with an interval that includes zero**. So the surface is flat within noise around
the declared point -- it is not dominated, and the weights are not a sensitive knob.
That is an argument for leaving them alone rather than for having chosen well.

The recorded consequence that prompted this run -- twenty minutes for four points
landing slightly above ninety minutes for four -- is not resolved by it. The surface
says the weights barely move the objective, which means that behaviour is not worth
buying a weight change to fix; it would need a different rule, and that would be a
candidate rather than a constant.

The locked holdout was not read. The panel is cut to the development seasons before
anything reads a feature window, so a holdout row cannot reach one even as
carry-over history.
