# Composite weekly population

`compose_composite_weeks` accepts frozen player-week inputs, a compact observed
LOAD model, a captured inventory, the first gameweek and caller-verified evidence.
It returns complete joint laws and separate input, model and intervention receipts
without fitting, file access or clock generation
(`src/squadopt/prediction/football_composite_weeks.py:81`,
`src/squadopt/prediction/football_composite_weeks.py:90`,
`src/squadopt/prediction/football_composite_weeks.py:366`).

Supply the complete declared roster, contiguous weeks, Premier League fixture
calendar and ordered deadlines. Each player requires one row per week, including
blanks. Fixture identity, club, opponent, home status, kickoff and order must
match the inventory. The caller must verify that the declaration matches the
retained capture; the pure function cannot authenticate external bytes or detect
a player omitted from both declaration and input
(`src/squadopt/prediction/football_composite_weeks.py:61`,
`src/squadopt/prediction/football_composite_weeks.py:146`,
`src/squadopt/prediction/football_composite_weeks.py:241`,
`src/squadopt/prediction/football_composite_weeks.py:366`).

Original native laws use the exact labels from `composite_native_sources`.
Calendar, snapshot, native components, native basis, role metadata and captured
eligibility retain separate identities. The first-week flag law must derive from
the same native law and bind the retained flag result. Later weeks refuse a flag
law. Every row's captured eligibility must equal the declared roster value
(`src/squadopt/prediction/football_composite_weeks.py:136`,
`src/squadopt/prediction/football_composite_weeks.py:241`,
`tests/unit/test_football_composite_weeks.py:558`).

All population, source and evidence checks precede prediction. LOAD runs only in
the first week, receiving its unchanged original native law. Its fitted multiplier
is transported onto that week's learned flag offset with mass proportional to
`q*l/p`. Resolved first-week news follows this transport. Later weeks receive one
shared captured-eligibility mixture of their native law, with no LOAD prediction
or LOAD lineage until a model is trained for those forecast horizons
(`src/squadopt/prediction/football_composite_weeks.py:366`,
`src/squadopt/prediction/football_joint_week_law.py:370`,
`tests/unit/test_football_composite_weeks.py:227`,
`tests/unit/test_football_composite_weeks.py:433`).

Transport refuses extrapolation outside native support. No-full-match evidence
preserves appearance through supported within-role redistribution; absence uses
an explicit deterministic intervention. A later player-week with eligibility
below one and zero native absent mass refuses the whole declared population
before prediction. One such unsupported row withholds the forecast for everyone
instead of being skipped
(`src/squadopt/prediction/football_composite_weeks.py:348`,
`src/squadopt/prediction/football_joint_week_law.py:370`,
`src/squadopt/prediction/football_joint_week_law.py:464`,
`tests/unit/test_football_composite_weeks.py:570`).

Each receipt records whether LOAD was applied. In later weeks `load_applied` is
false, the LOAD result hash equals the original native hash and the pre-evidence
law equals the eligibility offset. Receipts separately identify input, native,
offset and final laws, while the population, inventory and evidence have their
own hashes. The compact LOAD result hash remains distinct from the full fitted
metadata hash. These are inference composition policies with no accuracy claim
(`src/squadopt/prediction/football_composite_weeks.py:90`,
`src/squadopt/prediction/football_composite_weeks.py:366`).

The point-XI boundary requires each start probability to be at most one, even
though the composite accepts total atom mass within 1e-12 of one. A tolerated
rounding excess in start mass can therefore refuse fixture composition and
withhold the complete forecast; no player or fixture is silently dropped
(`src/squadopt/features/football_unit_point.py:32`,
`src/squadopt/prediction/football_composite_core.py:266`,
`src/squadopt/prediction/football_composite_core.py:674`).
