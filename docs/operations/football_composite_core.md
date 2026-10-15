# Composite fixture inference

The pure fixture entry point consumes retained native rows, final seven-atom minute
marginals, current source contexts and compact models. It returns fixture rows and a
separate composition receipt (`src/squadopt/prediction/football_composite_core.py:160`,
`src/squadopt/prediction/football_composite_core.py:174`,
`src/squadopt/prediction/football_composite_core.py:597`).

The caller must authenticate source bytes and complete weekly laws. The fixture core binds
their supplied digests and checks paired roster, club, position, clock, native fraction and
minute support consistency; it does not open sources or reconstruct a complete weekly law
from marginals (`src/squadopt/prediction/football_composite_core.py:1`,
`src/squadopt/prediction/football_composite_core.py:307`).

Unit, score and phase context records omit projected states. The core builds point units
from final starter probabilities, then applies unit rates, the score process, tactical
recipient heads and phase allocation. Original source records remain distinct from
derived point and tactical context source hashes
(`src/squadopt/prediction/football_composite_core.py:108`,
`src/squadopt/prediction/football_composite_core.py:123`,
`src/squadopt/prediction/football_composite_core.py:146`,
`src/squadopt/prediction/football_composite_core.py:643`,
`src/squadopt/prediction/football_composite_core.py:671`,
`src/squadopt/prediction/football_composite_core.py:776`).

The score input names the prospective unit-offset version. That version is excluded from
the unchanged historical native version inventory and explicitly refused by the ordinary
training header (`src/squadopt/features/football_score_state_inputs.py:21`,
`src/squadopt/features/football_score_state_inputs.py:300`,
`src/squadopt/features/football_score_state_inputs.py:380`).

Tactical offsets are rebuilt from original per-minute recipient weights and final expected
minutes. Phase weights divide tactical shares by final expected minutes once. The receipt
states that the tactical rate head is not evaluated and that zero phase coefficients are
not a claim of marginal identity under state normalization
(`src/squadopt/prediction/football_composite_core.py:476`,
`src/squadopt/prediction/football_composite_core.py:207`).

Final rows retain normal role fields and seven score survival moments. Clean-sheet points
use those survival moments; defensive contributions and conditional residuals use final
minute exposure. The existing nonnegative final FPL point convention is applied after
scoring, without clipping physical rates
(`src/squadopt/prediction/football_composite_core.py:500`).

The full bypass returns the original native JSON string without running family stages.
The default receipt stores stage input, result, compact artifact and original fit hashes.
Private audit callers can explicitly request full stage payloads without changing those
hashes or predictions (`src/squadopt/prediction/football_composite_core.py:182`,
`src/squadopt/prediction/football_composite_core.py:457`,
`src/squadopt/prediction/football_composite_core.py:597`).

Synthetic tests cover the independent FPL calculation, club credit closure, absence-driven
point replacement, same-role shorter exposure, exact bypass, source mismatches and both
historical training boundaries (`tests/unit/test_football_composite_core.py:1`).
