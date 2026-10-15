# Composite weekly population

`compose_composite_weeks` accepts frozen player-week inputs, a compact observed-LOAD
serving model, an explicit captured inventory, the first gameweek and caller-verified
evidence. Its result retains each complete joint law and separate input, model and
intervention receipts. The function performs no fitting, file access or clock generation
(`src/squadopt/prediction/football_composite_weeks.py:81`,
`src/squadopt/prediction/football_composite_weeks.py:90`,
`src/squadopt/prediction/football_composite_weeks.py:103`,
`src/squadopt/prediction/football_composite_weeks.py:359`).

Supply the full selected captured roster, contiguous target weeks, PL fixture calendar
and ordered deadlines. Every declared player requires one input in every declared week,
including a blank week. Fixture identity, club, opponent, home status, order and kickoff
must agree with the inventory. The source adapter owns verification that this declared
inventory actually equals the retained capture; the pure function cannot authenticate
external bytes or detect a player omitted from both the declaration and its inputs
(`src/squadopt/prediction/football_composite_weeks.py:61`,
`src/squadopt/prediction/football_composite_weeks.py:145`,
`src/squadopt/prediction/football_composite_weeks.py:240`,
`src/squadopt/prediction/football_composite_weeks.py:359`).

Build each original native law with the exact source labels returned by
`composite_native_sources`. The native components and retained flag result hashes identify
canonical complete JSON documents, including their fingerprint fields; a source adapter
must distinguish these identities from fingerprint calculations that omit that field.
The native basis, role metadata, calendar, capture and captured eligibility each retain
their own identities. The first-week flag law must bind the same original native law and
name its retained result under `retained_flag_result`. Later weeks refuse a flag law
(`src/squadopt/prediction/football_composite_weeks.py:61`,
`src/squadopt/prediction/football_composite_weeks.py:135`,
`src/squadopt/prediction/football_composite_weeks.py:240`,
`src/squadopt/live/football_artifact.py:66`).

All population, source, declared chronology and evidence checks run before the first
LOAD prediction. LOAD receives the unchanged original native week. The learned first-week
flag law supplies that week's offset; later weeks receive one shared captured-eligibility
mixture. The fitted LOAD multiplier is transported using mass proportional to `q*l/p`,
then resolved news is applied to the resulting law. Transport refuses an offset cell
outside native support. No-full-match evidence preserves appearance through supported
within-role redistribution; absence uses an explicitly recorded deterministic
intervention. These are inference composition policies, with no new calibration claim
(`src/squadopt/prediction/football_composite_weeks.py:359`,
`src/squadopt/prediction/football_joint_week_law.py:342`,
`src/squadopt/prediction/football_joint_week_law.py:370`,
`src/squadopt/prediction/football_joint_week_law.py:464`).

The result separates the compact LOAD result hash from the full training-metadata hash.
Each weekly receipt identifies original native, LOAD result, selected offset, pre-evidence
and final laws. The input-population hash covers the ordered weekly input hashes; the
inventory and evidence have separate hashes. Single-fixture, dependent double-fixture
and blank-week arithmetic, source mismatches, double eligibility, late malformed rows
and pre-prediction evidence rejection have focused tests
(`src/squadopt/prediction/football_composite_weeks.py:90`,
`src/squadopt/prediction/football_composite_weeks.py:103`,
`src/squadopt/prediction/football_composite_weeks.py:359`,
`tests/unit/test_football_composite_weeks.py:225`,
`tests/unit/test_football_composite_weeks.py:296`).
