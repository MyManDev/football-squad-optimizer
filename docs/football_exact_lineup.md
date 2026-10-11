# Explicit exact fixed-fifteen role search

Issue [#1054](https://github.com/MyManDev/football-squad-optimizer/issues/1054)
adds a pure, separately invoked role engine. It has no live caller in this step.
The accepted advice routes, bounded 128-score search, multiweek budgets, forecasts,
transfers, purchase lots, bank, free transfers and chip selection remain unchanged.
Step 2 requires this engine and #1049 to actually merge, followed by a separate
explicit experimental one-week integration and shared-planning review.

## Interface and scope

`squadopt.planning.football_exact_lineup.optimize_football_lineup_exact` accepts
the selected fifteen, an incumbent XI, its ordered bench, captain and vice. Keyword
arguments carry the already selected chip, actual transfer charge, starter and
captain exclusions, and a complete first-action lock. Both captain roles must be
in the XI. The incumbent must be legal and satisfy the supplied exclusions;
unknown restricted identifiers are refused. Inputs and returned multiplier maps
remain immutable.

The return value retains the original complete action and the best action, with
counts of legal XIs, reserve orders, complete pair scores, built score records,
covered captain pairs, precomputed coefficient terms, actual pair membership
checks, convolution states and cache use. The search version is
`exact_fixed_fifteen_roles_v1`. The score continues to use the published
`independent_appearance_lineup_v1` contract.

Unrestricted legal outfield formations have these numbers of selections:

| DEF | MID | FWD | Outfield selections |
| --- | --- | --- | --- |
| 3 | 4 | 3 | 50 |
| 3 | 5 | 2 | 30 |
| 4 | 3 | 3 | 50 |
| 4 | 4 | 2 | 75 |
| 4 | 5 | 1 | 15 |
| 5 | 2 | 3 | 10 |
| 5 | 3 | 2 | 30 |
| 5 | 4 | 1 | 15 |

These sum to 275. Two starting goalkeeper choices give 550 legal XIs, each with
six ordered outfield reserve actions, giving 3300 arrangements. All 110 eligible
ordered captain/vice pairs are compared for every XI/bench arrangement, giving
363000 complete pair scores. The 210 possible squad-wide ordered pairs have
their captain and vice coefficient terms precomputed; no separately rounded
two-term bonus is used to rank them. There are 60500 covered XI/pair combinations
before the six reserve orders. Pair membership checks are recorded separately.
Fingerprinted score records are built only for the incumbent and subsequent
strictly improving complete actions. Building each record also recalculates its
full score and checks equality with the pair comparison. Thus
`role_scores_evaluated` is the number of pair comparisons plus built records,
including the incumbent; this verification work is counted too. Restrictions
reduce this menu. A lock leaves exactly its original complete action, including
tuple order, reserve priority and vice, with `locked_complete_action_only` scope.

The unrestricted proof scope is
`all_legal_fixed_fifteen_roles_under_independent_appearance`. This proves the best
role action on the supplied points, appearances, chip and restrictions for this
already selected fifteen. It does not prove the best fifteen, transfers, chip,
forecast, joint team-absence model or realized future score. Calculations use
finite floating-point inputs and deterministic summation; no score tolerance or
Monte Carlo sampling is used.

Every pair comparison uses the inherited scorer's exact coefficient operations:
starter coefficient `1.0`, captain coefficient `1.0 + k`, and vice coefficient
`1.0 + k * (1 - q_c)`. Captain and vice both start, so neither has an autosub
coefficient. Their terms replace the corresponding entries in the complete
canonical fifteen-term list; `math.fsum` sums that list before the actual charge
is subtracted. Pre-rounding a baseline or captain-bonus subgroup can hide a
genuine difference after signed-point cancellation. A regression with captain
mean one, another starter at minus two and vice means `1e-16` versus `1.1e-16`
demonstrates the difference. Normal, Triple Captain and Bench Boost cases are
checked against every pair's inherited complete score without a tolerance.

## Score and participation contract

For unconditional weekly points `mu_i` and positive-minute weekly appearance
`q_i`, the inherited expectation is:

```text
U = sum(mu_i for starters)
  + sum(a_i * mu_i for reserves)
  + k * (mu_c + (1 - q_c) * mu_v)
  - actual_transfer_charge
```

`a_i` is substitute admission conditional on that incoming player appearing. Its
own appearance is already in `mu_i` and is not multiplied again. `k` is one
normally and two for Triple Captain. Bench Boost counts all fifteen unconditional
point means and captain fallback, with no autosub addition. Wildcard and Free Hit
use the same fixed-squad score; this engine does not transact either chip.

The inherited scorer assumes independent player weekly appearances and
conditional point means unaffected by other players' appearances. Double-week
inputs must already aggregate any positive minutes and total weekly points.
Signed points are supported, but `q=0` requires `mu=0`; nonfinite or missing
appearance inputs are refused. Forecast eligibility has already been applied
upstream. No fixture strength, injury percentage or team multiplier is added.

The [official FPL rules](https://www.premierleague.com/en/news/4661029), checked
9 October 2026, require legal formations, priority-order outfield substitutions,
separate goalkeeper cover and captain fallback. Any positive-minute cameo blocks
replacement. The rules also distinguish participation through a zero-minute card
from minutes used for captain fallback. The current positive-minute appearance
contract cannot represent that separate event. Card-only cases remain explicitly
outside the score assumptions. Supporting them requires separate forecast
participation evidence and a versioned joint event contract, rather than treating
one marginal appearance input as both events or inventing card rates.

Expected net points are primary. Only exactly equal point scores prefer the XI
with the larger sum of effective appearances. Equal sums retain the earlier full
action, with the original incumbent seeded first. Even a tiny positive point
difference precedes this availability tie. Equivalent XI sets use canonical
player order for convolutions, so input table and XI ordering cannot change their
appearance arithmetic.

## Enumeration and synthetic verification

The engine enumerates every legal outfield selection, both allowed goalkeepers
and all six reserve orders. It reuses the existing published exact autosub scorer.
For an XI it convolves absent starters by position, then evaluates the three
reserves' eight appearance patterns. Outfield admission work is shared between
the two goalkeeper choices, while goalkeeper cover is recalculated separately.
There are at most 1650 distinct outfield arrangement convolutions; the reported
state ledger counts work actually performed. Captain changes reuse that work.

`tests/unit/test_football_exact_lineup.py` independently enumerates arbitrary
11-of-15 subsets, all reserve orders and all eligible pairs using finite
appearance worlds. Its oracle greedily replaces individual absent starter slots,
without the engine's count convolution. That independent identity-based oracle
is separately checked against the official realized scorer in all eight legal
formations using one-minute cameos. Global optimal scores are checked for normal,
Triple Captain and Bench Boost actions, including signed points and endpoint
appearances. A strict simultaneous two-player XI improvement lies outside the
existing one-swap neighborhood.

Additional tests cover goalkeeper cover, constraints on both captain roles,
complete locks, exact point and availability ties, tiny point gains, identifier
and row-order invariance, immutability, validation refusal and the unchanged
bounded cap. Existing scorer tests run alongside them. All inputs are synthetic;
no live squad, archive, current outcome, forecast artifact or weekly run is used.

Focused reproduction from this worktree in PowerShell:

```powershell
$env:PYTHONPATH="$PWD/src;$PWD"
$env:PYTHONUTF8='1'
& 'C:/Users/ertug/Desktop/MyManDev/projects/football-squad-optimizer/.venv/Scripts/python.exe' -m pytest tests/unit/test_football_exact_lineup.py tests/unit/test_expected_lineup.py -q
```

Final focused validation passed 100 unique cases: 48 new exact-engine cases and
52 existing scorer cases. Six sequential source mutations produced eleven
expected test failures: incomplete XI enumeration, omitted captain fallback,
availability placed before points, omitted goalkeeper cover, ignored full
locks and rounded partial captain-bonus ranking. Source bytes were restored after
every mutation and the full focused 100-case run passed again. Ruff check/format,
source mypy and all six import contracts passed.

## Synthetic timing on the owner's PC

On 9 October 2026, the final pure engine performed these complete synthetic
enumerations. Each visited 550 XIs and 3300 reserve orders, compared 363000 full
pair scores plus the original incumbent, precomputed 210 coefficient-term pairs,
and covered 60500 eligible XI/pair combinations. Each performed 115500 pair
membership checks. The timing table below includes additional full-score
calculations when fingerprinted records are built.

| Synthetic appearance inputs | Seconds | Actual convolution states | Built records | Total full scores |
| --- | --- | --- | --- | --- |
| All fifteen at 0.5 | 7.522 | 982320 | 11 | 363011 |
| Varied inputs strictly between zero and one | 9.373 | 982320 | 10 | 363010 |
| All fifteen at one | 0.386 | 1650 | 8 | 363008 |

The uncertain cases exercise every missing-count and reserve-appearance state
in every legal arrangement. The varied case uses 13 distinct inputs across the
fifteen rows. These are individual local elapsed observations, not isolated CPU
benchmarks or upper latency bounds. They measure role enumeration separately
from transfer-solver work and establish no interactive latency commitment. Step
2 must assess its complete request budget before adding an explicit invocation.

Reproduce these synthetic cases with the same venv and `PYTHONPATH`:

```powershell
@'
from time import perf_counter
import pandas as pd
from squadopt.planning.football_exact_lineup import optimize_football_lineup_exact
xi = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
bench = (2, 6, 7, 12)
cases = [
    ("uniform_half", [.5] * 15),
    ("varied_uncertain", [.15 + .7 * ((p * 7) % 13) / 12 for p in range(1, 16)]),
    ("certain", [1.] * 15),
]
for name, chances in cases:
    squad = pd.DataFrame({
        "player_id": list(range(1, 16)),
        "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
        "expected_points": [(p % 7 + 1) * q for p, q in zip(range(1, 16), chances)],
        "appearance_probability": chances,
    })
    started = perf_counter()
    result = optimize_football_lineup_exact(squad, xi, bench, 13, 8)
    print(name, perf_counter() - started, result.legal_xis,
          result.reserve_orders_evaluated, result.states_evaluated,
          result.captain_pair_scores_evaluated, result.score_records_built,
          result.role_scores_evaluated, result.captain_pair_membership_checks)
'@ | & 'C:/Users/ertug/Desktop/MyManDev/projects/football-squad-optimizer/.venv/Scripts/python.exe' -
```
