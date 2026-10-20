# Joint weekly minute law composition

`JointWeekLaw` is a pure immutable player-week distribution. It retains ordered fixture
identities, seven role/minute atoms per fixture, the complete Cartesian weekly state
inventory, fixed role metadata and operation lineage. It performs no fitting or source
I/O. The native constructor normalizes supplied mass once within the existing native-law
tolerance; a blank week contains one empty state
(`src/squadopt/prediction/football_joint_week_law.py:47`,
`src/squadopt/prediction/football_joint_week_law.py:137`,
`src/squadopt/prediction/football_joint_week_law.py:249`,
`src/squadopt/features/football_load_inputs.py:251`).

## Compose model outputs

Create the native law with `make_joint_week_law`, then bind caller-verified flag and native
LOAD outputs using `model_week_law`. Explicit state tuples must match the canonical native
order. Model outputs retain every native structural zero and positive cell. Fixture order,
per-atom minutes and role metadata cannot change during transport
(`src/squadopt/prediction/football_joint_week_law.py:288`,
`src/squadopt/prediction/football_joint_week_law.py:322`).

Use the learned first-week flag law directly as the LOAD offset. For later weeks,
`apply_shared_eligibility` supplies one shared weekly event: `q = e*p + (1-e)*delta_absent`.
The helper accepts an unadjusted native law, so a flag-adjusted law cannot receive the
captured multiplier again. This mixture differs from independent per-fixture eligibility
(`src/squadopt/prediction/football_joint_week_law.py:342`,
`tests/unit/test_football_joint_week_law.py:147`).

For native law `p`, its fitted LOAD result `l` and offset `q`, `transport_load` returns mass
proportional to `q*l/p`. The original LOAD normalization cancels, so this applies the same
learned multiplier to the supplied offset. It records all three law identities and refuses
positive offset cells outside native support or numerical loss of positive offset mass.
An unchanged LOAD result returns the exact offset probabilities. This is an explicit
inference transport policy, not training or calibration on the flagged offset
(`src/squadopt/prediction/football_joint_week_law.py:370`,
`tests/unit/test_football_joint_week_law.py:105`,
`tests/unit/test_football_joint_week_law.py:132`).

## Apply verified evidence last

The caller owns source-byte, quote, timing and conflict checks. Pass only resolved first-week
claims with matching person/week and exact fixture IDs. An absence claim must name every
affected fixture explicitly. Duplicate evidence and overlapping fixture scopes are refused;
the helper does not silently choose between absence and a minute restriction
(`src/squadopt/prediction/football_joint_week_law.py:72`,
`src/squadopt/prediction/football_joint_week_law.py:464`).

For `no_full_match`, each fixed other-fixture state is handled separately. Full-match mass
moves to already-positive shorter cells in the same starting or cameo role, preserving
their ratio. A positive full-match cell without same-role shorter support in that slice
is refused, even when marginal shorter support exists. This extends the existing same-role
single-fixture policy without rebuilding independent fixture marginals
(`src/squadopt/prediction/football_joint_week_law.py:437`,
`src/squadopt/live/minute_evidence.py:655`,
`tests/unit/test_football_joint_week_law.py:174`,
`tests/unit/test_football_joint_week_law.py:216`).

The redistribution preserves the joint absence/start/cameo pattern, weekly appearance and
each fixture appearance, within floating-point tolerance. Absence deterministically maps
the scoped fixture state to zero. Both preserve the full joint marginal of unaffected
fixtures. Multiple restrictions run atomically in native fixture order; no-full-match
changes minute-bin dependence and does not claim identical correlations afterward
(`src/squadopt/prediction/football_joint_week_law.py:428`,
`src/squadopt/prediction/football_joint_week_law.py:464`,
`tests/unit/test_football_joint_week_law.py:195`,
`tests/unit/test_football_joint_week_law.py:246`).

Shared eligibility and verified absence have an explicit structural-intervention exception:
their deterministic absent destinations may previously have had zero probability. Newly
supported absent indices are recorded in lineage. This is not native zero preservation.
LOAD transport and no-full-match have no such exception; an absent cell created outside
native support cannot acquire an undefined LOAD likelihood ratio
(`src/squadopt/prediction/football_joint_week_law.py:37`,
`src/squadopt/prediction/football_joint_week_law.py:342`,
`src/squadopt/prediction/football_joint_week_law.py:370`,
`tests/unit/test_football_joint_week_law.py:163`,
`tests/unit/test_football_joint_week_law.py:228`).

## Serialize and inspect

`joint_week_marginals` extracts coherent weekly appearance, fixture probabilities, expected
minutes and start/cameo probabilities from the full law. Document encoders return detached
JSON-compatible objects. Readers require exact recursive field inventories, bounded arrays
and validated scalar types, restoring frozen tuples and lineage. The outer JSON reader must
reject duplicate keys before passing a decoded object. The law digest is canonical sorted
JSON; source hashes and parent identities remain caller-supplied references, not proof that
this helper fetched source bytes or authenticated a model. No source or training clock is
invented by these operations
(`src/squadopt/prediction/football_joint_week_law.py:226`,
`src/squadopt/prediction/football_joint_week_law.py:540`,
`src/squadopt/prediction/football_joint_week_law.py:555`,
`src/squadopt/prediction/football_joint_week_law.py:573`,
`src/squadopt/prediction/football_joint_week_law.py:624`).
