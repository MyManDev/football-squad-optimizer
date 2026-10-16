# Composite fixture inference

The pure fixture entry point consumes retained native rows, final seven-atom minute
marginals, current source contexts and compact models. It returns fixture rows and a
separate composition receipt (`src/squadopt/prediction/football_composite_core.py:161`,
`src/squadopt/prediction/football_composite_core.py:175`,
`src/squadopt/prediction/football_composite_core.py:617`).

The caller must authenticate source bytes and complete weekly laws. The fixture core binds
their supplied digests and checks paired roster, club, position, clock, native fraction and
minute support consistency. The original native digest must agree across the root, score
and tactical contexts, and every consumed source acquisition must precede assembly
(`src/squadopt/prediction/football_composite_core.py:329`,
`src/squadopt/prediction/football_composite_core.py:333`,
`src/squadopt/prediction/football_composite_core.py:358`). It does not open sources or reconstruct a complete weekly law
from marginals (`src/squadopt/prediction/football_composite_core.py:1`,
`src/squadopt/prediction/football_composite_core.py:308`).

Unit, score and phase context records omit projected states. The core builds point units
from final starter probabilities, then applies unit rates, the score process, tactical
recipient heads and phase allocation. Original source records remain distinct from
derived point and tactical context source hashes
(`src/squadopt/prediction/football_composite_core.py:109`,
`src/squadopt/prediction/football_composite_core.py:124`,
`src/squadopt/prediction/football_composite_core.py:147`,
`src/squadopt/prediction/football_composite_core.py:664`,
`src/squadopt/prediction/football_composite_core.py:691`,
`src/squadopt/prediction/football_composite_core.py:796`).

The score input names the prospective unit-offset version. That version is excluded from
the unchanged historical native version inventory and explicitly refused by the ordinary
training header (`src/squadopt/features/football_score_state_inputs.py:21`,
`src/squadopt/features/football_score_state_inputs.py:300`,
`src/squadopt/features/football_score_state_inputs.py:380`).

Tactical offsets are rebuilt from original per-minute recipient weights and final expected
minutes. Phase weights divide tactical shares by final expected minutes once. The receipt
states that the tactical rate head is not evaluated and that zero phase coefficients are
not a claim of marginal identity under state normalization
(`src/squadopt/prediction/football_composite_core.py:496`,
`src/squadopt/prediction/football_composite_core.py:208`).

Final rows retain normal role fields and seven score survival moments. Clean-sheet points
use those survival moments; defensive contributions and conditional residuals use final
minute exposure. The existing nonnegative final FPL point convention is applied after
scoring, without clipping physical rates
(`src/squadopt/prediction/football_composite_core.py:520`).

The full bypass returns the original native JSON string without running family stages.
The default receipt stores stage input, result, compact artifact and original fit hashes.
Private audit callers can explicitly request full stage payloads without changing those
hashes or predictions (`src/squadopt/prediction/football_composite_core.py:183`,
`src/squadopt/prediction/football_composite_core.py:477`,
`src/squadopt/prediction/football_composite_core.py:617`).

Synthetic tests cover the independent FPL calculation, club credit closure, absence-driven
point replacement, same-role shorter exposure, exact bypass, source mismatches and both
historical training boundaries (`tests/unit/test_football_composite_core.py:1`).

Both duty contexts must name the exact retained FPL snapshot, fingerprint and capture
time. The recipe refuses another capture even when its clocks would otherwise pass;
the fixture core also rejects Git replay identities and mixed duty captures
(`src/squadopt/live/football_composite_basis.py:280`,
`src/squadopt/prediction/football_composite_core.py:370`).
Family targets are bound to the first captured forecast week before the recipe is
recomputed (`src/squadopt/live/football_composite_basis.py:293`).

The tactical recipient and phase models were fitted with native share offsets, then
their corrections are stacked here: tactical shares become the phase offsets.
Shared effects, including role and position, can therefore be applied twice. This
composition has no claim to remove that overlap or improve predictive accuracy;
an accuracy reading would need to address that modeling limitation
(`src/squadopt/prediction/football_observed_tactical.py:558`,
`src/squadopt/prediction/football_phase_duties.py:175`,
`src/squadopt/prediction/football_phase_duties.py:222`,
`src/squadopt/prediction/football_composite_core.py:859`).

The derived unit offset can be constructed by the typed composition, but the raw score
snapshot reader refuses a document that claims this internal model identity
(`src/squadopt/features/football_score_state_inputs.py:629`).
